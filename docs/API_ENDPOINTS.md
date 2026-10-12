# Aragora API Documentation

This document describes the HTTP API endpoints provided by the Aragora server.

## Table of Contents

- [Admin](#admin)
- [ApiDocs](#apidocs)
- [Backup Handler](#backup-handler)
- [Backup Offsite Handler](#backup-offsite-handler)
- [Credits](#credits)
- [Dashboard](#dashboard)
- [Docs](#docs)
- [Feature Flags](#feature-flags)
- [Feature Flags Read](#feature-flags-read)
- [Admin](#admin)
- [BuildInfo](#buildinfo)
- [DeployStatus](#deploystatus)
- [Liveness](#liveness)
- [Readiness](#readiness)
- [StorageHealth](#storagehealth)
- [Metrics Dashboard](#metrics-dashboard)
- [Mfa Compliance](#mfa-compliance)
- [Nomic Admin](#nomic-admin)
- [Rotation Status](#rotation-status)
- [Security](#security)
- [System](#system)
- [System Health](#system-health)
- [System Intelligence](#system-intelligence)
- [Users](#users)
- [AgentBridge](#agentbridge)
- [Agents](#agents)
- [Calibration](#calibration)
- [External Agents](#external-agents)
- [Feedback](#feedback)
- [Feedback Hub](#feedback-hub)
- [Harnesses](#harnesses)
- [Introspection](#introspection)
- [Laboratory](#laboratory)
- [LeaderboardView](#leaderboardview)
- [Persona](#persona)
- [Probes](#probes)
- [AgentRecommendation](#agentrecommendation)
- [Selection](#selection)
- [Verticals](#verticals)
- [AnalyticsPerformance](#analyticsperformance)
- [DecisionAnalytics](#decisionanalytics)
- [ModerationAnalytics](#moderationanalytics)
- [OutcomeAnalytics](#outcomeanalytics)
- [SpendAnalytics](#spendanalytics)
- [Agent Evolution Dashboard](#agent-evolution-dashboard)
- [Dashboard](#dashboard)
- [Differentiation](#differentiation)
- [AnalyticsDashboard](#analyticsdashboard)
- [Outcome Dashboard](#outcome-dashboard)
- [Handler](#handler)
- [RBAC](#rbac)
- [SCIM](#scim)
- [Signup Handlers](#signup-handlers)
- [SSO](#sso)
- [Autonomous Learning](#autonomous-learning)
- [Gastown Dashboard](#gastown-dashboard)
- [Monitoring](#monitoring)
- [Nomic](#nomic)
- [RalphDashboard](#ralphdashboard)
- [Self Improve](#self-improve)
- [Self Improve Details](#self-improve-details)
- [Budgets](#budgets)
- [CostDashboard](#costdashboard)
- [UsageMetering](#usagemetering)
- [UsageMetering](#usagemetering)
- [Email Webhook](#email-webhook)
- [Slack](#slack)
- [Handler](#handler)
- [IdeaCanvas](#ideacanvas)
- [Marketplace](#marketplace)
- [MarketplaceBrowse](#marketplacebrowse)
- [Marketplace Pilot](#marketplace-pilot)
- [Playbook](#playbook)
- [Skill Marketplace](#skill-marketplace)
- [Skills](#skills)
- [TemplateDiscovery](#templatediscovery)
- [Workflow Templates](#workflow-templates)
- [Code Review](#code-review)
- [Dependency Analysis](#dependency-analysis)
- [Intelligence](#intelligence)
- [Metrics](#metrics)
- [Quick Scan](#quick-scan)
- [Reviews](#reviews)
- [Audit Trail](#audit-trail)
- [Data Classification Handler](#data-classification-handler)
- [Compliance](#compliance)
- [Queue](#queue)
- [Cost](#cost)
- [Audience Suggestions](#audience-suggestions)
- [Auditing](#auditing)
- [Belief](#belief)
- [DebateDecisionBridge](#debatedecisionbridge)
- [Composite](#composite)
- [Context Budget](#context-budget)
- [Critique](#critique)
- [Debate Intervention](#debate-intervention)
- [Debate Stats](#debate-stats)
- [Deliberations](#deliberations)
- [Handler](#handler)
- [HybridDebate](#hybriddebate)
- [Moments](#moments)
- [Tournaments](#tournaments)
- [Decision](#decision)
- [Explainability](#explainability)
- [Pipeline](#pipeline)
- [Receipts](#receipts)
- [Playground](#playground)
- [EmailDebate](#emaildebate)
- [Email Services](#email-services)
- [EmailTriage](#emailtriage)
- [Email](#email)
- [Ab Testing](#ab-testing)
- [Cross Pollination](#cross-pollination)
- [Genesis](#genesis)
- [Handler](#handler)
- [Replays](#replays)
- [Training](#training)
- [ExamplePermission](#examplepermission)
- [Advertising](#advertising)
- [AnalyticsPlatforms](#analyticsplatforms)
- [Audio](#audio)
- [AuditSessions](#auditsessions)
- [Broadcast](#broadcast)
- [Handler](#handler)
- [Connectors](#connectors)
- [CRM](#crm)
- [Cross Platform Analytics](#cross-platform-analytics)
- [Handler](#handler)
- [Documents](#documents)
- [DocumentBatch](#documentbatch)
- [Ecommerce](#ecommerce)
- [Email Webhooks](#email-webhooks)
- [Features](#features)
- [GmailLabels](#gmaillabels)
- [GmailThreads](#gmailthreads)
- [Integrations](#integrations)
- [Legal](#legal)
- [Handler](#handler)
- [Outlook](#outlook)
- [Plugins](#plugins)
- [Pulse](#pulse)
- [Reconciliation](#reconciliation)
- [RoutingRules](#routingrules)
- [Support](#support)
- [Handler](#handler)
- [Status](#status)
- [Accounting](#accounting)
- [Ap Automation](#ap-automation)
- [Ar Automation](#ar-automation)
- [Expenses](#expenses)
- [Invoices](#invoices)
- [GatewayAgents](#gatewayagents)
- [GatewayConfig](#gatewayconfig)
- [GatewayCredentials](#gatewaycredentials)
- [Gateway](#gateway)
- [GatewayHealth](#gatewayhealth)
- [Gauntlet](#gauntlet)
- [Audit Bridge](#audit-bridge)
- [Pr Review](#pr-review)
- [UnifiedApprovals](#unifiedapprovals)
- [Moderation](#moderation)
- [Outcome](#outcome)
- [ReviewQueue](#reviewqueue)
- [Settlement](#settlement)
- [Inbox Command](#inbox-command)
- [Team Inbox](#team-inbox)
- [InboxTrustWedge](#inboxtrustwedge)
- [Automation](#automation)
- [Bindings](#bindings)
- [ComputerUse](#computeruse)
- [ERC8004](#erc8004)
- [Health](#health)
- [Integration Management](#integration-management)
- [Adapters](#adapters)
- [KMCheckpoint](#kmcheckpoint)
- [KnowledgeChat](#knowledgechat)
- [RLMContext](#rlmcontext)
- [Knowledge](#knowledge)
- [KnowledgeMound](#knowledgemound)
- [Consensus](#consensus)
- [Insights](#insights)
- [Learning](#learning)
- [Memory](#memory)
- [Memory Analytics](#memory-analytics)
- [Handler](#handler)
- [Metrics Endpoint](#metrics-endpoint)
- [Devices](#devices)
- [NotificationHistory](#notificationhistory)
- [NotificationPreferences](#notificationpreferences)
- [NotificationTemplates](#notificationtemplates)
- [Oauth Wizard](#oauth-wizard)
- [Crashes](#crashes)
- [Dashboard](#dashboard)
- [EndpointAnalytics](#endpointanalytics)
- [Slo](#slo)
- [Gateway](#gateway)
- [Coordination](#coordination)
- [Handler](#handler)
- [PaymentRoutes](#paymentroutes)
- [Decomposition](#decomposition)
- [PipelineExecute](#pipelineexecute)
- [Pipeline Graph](#pipeline-graph)
- [PlanManagement](#planmanagement)
- [ProvenanceExplorer](#provenanceexplorer)
- [Receipts](#receipts)
- [PipelineTransitions](#pipelinetransitions)
- [UniversalGraph](#universalgraph)
- [Platform Config](#platform-config)
- [Handler](#handler)
- [Gallery](#gallery)
- [StatusPage](#statuspage)
- [Security Debate](#security-debate)
- [Threat Intel](#threat-intel)
- [SharedInbox](#sharedinbox)
- [Feedback](#feedback)
- [Onboarding](#onboarding)
- [ReadinessCheck](#readinesscheck)
- [SMEUsageDashboard](#smeusagedashboard)
- [ChannelHealth](#channelhealth)
- [Collaboration](#collaboration)
- [Discord Oauth](#discord-oauth)
- [Notifications](#notifications)
- [Relationship](#relationship)
- [Slack Oauth](#slack-oauth)
- [Social Media](#social-media)
- [Teams Oauth](#teams-oauth)
- [Spectate Ws](#spectate-ws)
- [TaskExecution](#taskexecution)
- [TaskQueue](#taskqueue)
- [Benchmarking](#benchmarking)
- [Evaluation](#evaluation)
- [Verification](#verification)
- [Voice](#voice)
- [Webhook](#webhook)
- [WorkflowBuilder](#workflowbuilder)
- [Workflow](#workflow)
- [TemplateRegistry](#templateregistry)
- [Workspace Module](#workspace-module)

---

## Admin

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

## ApiDocs

Handler for API documentation and introspection endpoints.

### `GET` `/api/v1/docs/openapi.json`

GET /api/v1/docs/openapi.json

### `GET` `/api/v1/docs/routes`

Return a lightweight summary of all registered routes

### `GET` `/api/v1/docs/stats`

Return API statistics: endpoint counts by tag and method

---

## Backup Handler

Backup HTTP Handlers for Aragora.

### `GET` `/api/v2/backups` 🔒

List backups with filters

### `POST` `/api/v2/backups` 🔒

Create new backup

### `GET` `/api/v2/backups/:backup_id` 🔒

Get specific backup metadata

### `DELETE` `/api/v2/backups/:backup_id` 🔒

Delete a backup

---

## Backup Offsite Handler

Backup Offsite and Restore Drill HTTP Handlers.

### `GET` `/api/v1/backup/status` 🔒

Current backup status and last successful backup

### `GET` `/api/v1/backup/drills` 🔒

List restore drill results

### `POST` `/api/v1/backup/drill` 🔒

Trigger a manual restore drill

---

## Credits

Credits Admin API Handler.

### `POST` `/api/v1/admin/credits/{org_id}/issue` 🔒

Issue credits to organization

### `GET` `/api/v1/admin/credits/{org_id}` 🔒

Get credit account details

### `GET` `/api/v1/admin/credits/{org_id}/transactions` 🔒

List credit transactions

### `POST` `/api/v1/admin/credits/{org_id}/adjust` 🔒

Make balance adjustment

---

## Dashboard

Handler for dashboard endpoint.

### `GET` `/api/dashboard/debates`

Get consolidated debate metrics for dashboard

### `POST` `/api/v1/dashboard`

Get consolidated debate metrics for dashboard

### `GET` `/api/v1/dashboard/overview` 🔒

GET /api/v1/dashboard/overview

### `GET` `/api/v1/dashboard/debates`

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

### `POST` `/api/v1/dashboard/export`

POST /api/v1/dashboard/export

### `GET` `/api/v1/dashboard/quality-metrics` 🔒

GET /api/v1/dashboard/quality-metrics

---

## Docs

API documentation endpoint handlers.

### `GET` `/api/openapi`

OpenAPI 3.0 JSON specification

### `GET` `/api/openapi.json`

OpenAPI 3.0 JSON specification

### `GET` `/api/openapi.yaml`

OpenAPI 3.0 YAML specification

### `GET` `/api/postman.json`

Postman collection export

### `GET` `/api/docs`

Swagger UI interactive documentation

### `GET` `/api/redoc`

ReDoc API documentation viewer

---

## Feature Flags

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

## Feature Flags Read

Feature flags handler for reading flag values.

### `GET` `/api/v1/feature-flags`

List all feature flags with current values

### `GET` `/api/v1/feature-flags/:name` 🔒

Get a specific flag value

---

## Admin

Handler for admin endpoints.

### `GET` `/api/v1/admin/organizations` 🔒

GET /api/v1/admin/organizations

### `GET` `/api/v1/admin/users` 🔒

GET /api/v1/admin/users

### `GET` `/api/v1/admin/stats` 🔒

GET /api/v1/admin/stats

### `GET` `/api/v1/admin/system/metrics` 🔒

GET /api/v1/admin/system/metrics

### `GET` `/api/v1/admin/impersonate`

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

### `GET` `/api/v1/admin/circuit-breakers`

GET /api/v1/admin/circuit-breakers

### `GET` `/api/v1/admin/circuit-breakers/reset`

GET /api/v1/admin/circuit-breakers/reset

---

## BuildInfo

Handler for the /health/build endpoint.

### `GET` `/health/build`

Return build SHA, time, and version

### `GET` `/api/health/build`

Return build SHA, time, and version

### `GET` `/api/v1/health/build`

Return build SHA, time, and version

---

## DeployStatus

Handler for the deploy status endpoint.

### `GET` `/api/v1/deploy/status` 🔒

Return comprehensive deploy status

---

## Liveness

Handler for the /healthz liveness probe endpoint.

### `GET` `/healthz`

GET /healthz

---

## Readiness

Handler for /readyz readiness probe endpoints.

### `GET` `/readyz`

GET /readyz

### `GET` `/readyz/dependencies`

Full dependency validation probe

---

## StorageHealth

Handler for storage and database health check endpoints.

### `GET` `/api/v1/health/stores`

Check health of all database stores

### `GET` `/api/v1/health/database`

Check health of consolidated database schema

### `GET` `/api/health/stores`

Check health of all database stores

---

## Metrics Dashboard

Admin Metrics Dashboard Endpoints.

### `GET` `/api/v1/admin/stats` 🔒

Get system-wide statistics

### `GET` `/api/v1/admin/system/metrics` 🔒

Get aggregated system metrics

### `GET` `/api/v1/admin/revenue` 🔒

Get revenue and billing statistics

---

## Mfa Compliance

MFA Compliance Dashboard endpoint handler.

### `GET` `/api/v1/admin/mfa-compliance` 🔒

Aggregate MFA status for all admin users

---

## Nomic Admin

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

## Rotation Status

Key Rotation Status Admin Handler.

### `GET` `/api/v1/admin/security/rotation-status` 🔒

Get rotation status for all managed secrets

### `GET` `/api/admin/security/rotation-status` 🔒

(non-versioned backward compat)

---

## Security

Security endpoint handlers.

### `GET` `/api/admin/security/status` 🔒

Get encryption and key status

### `POST` `/api/admin/security/rotate-key`

Rotate encryption key

### `GET` `/api/admin/security/health` 🔒

Check encryption health

---

## System

System and utility endpoint handlers.

### `GET` `/api/history/cycles`

Get cycle history

### `GET` `/api/history/events`

Get event history

### `GET` `/api/history/debates`

Get debate history

### `GET` `/api/history/summary`

Get history summary

---

## System Health

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

## System Intelligence

System Intelligence Dashboard Handler.

### `GET` `/api/v1/system-intelligence/overview`

High-level system stats

### `GET` `/api/v1/system-intelligence/agent-performance`

ELO, calibration, win rates

### `GET` `/api/v1/system-intelligence/institutional-memory`

Cross-debate injection stats

### `GET` `/api/v1/system-intelligence/improvement-queue`

Queue contents + breakdown

### `GET` `/api/v1/system-intelligence/anomalies`

Recent anomaly alerts

### `GET` `/api/v1/system-intelligence/events`

Recent system events

### `GET` `/api/v1/system-intelligence/km-sync`

Knowledge sync status

### `GET` `/api/v1/system-intelligence/nomic-status`

Nomic loop status

### `GET` `/api/v1/system-intelligence/debate-queue`

Debate activity summary

---

## Users

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

## AgentBridge

Expose persisted agent-bridge state and feature-gated operator writes.

### `GET` `/api/v1/agent-bridge/runs` 🔒

GET /api/v1/agent-bridge/runs

### `POST` `/api/v1/agent-bridge/runs` 🔒

POST /api/v1/agent-bridge/runs

---

## Agents

Agent-related endpoint handlers.

### `GET` `/api/leaderboard`

Get agent rankings

### `GET` `/api/rankings`

Get agent rankings (alias)

### `GET` `/api/agents/local`

List detected local LLM servers

### `GET` `/api/agents/local/status`

Get local LLM availability status

### `GET` `/api/agent/{name}/profile`

Get agent profile

### `GET` `/api/agent/{name}/history`

Get agent match history

### `GET` `/api/agent/{name}/calibration`

Get calibration scores

### `GET` `/api/agent/{name}/consistency`

Get consistency score

### `GET` `/api/agent/{name}/flips`

Get agent flip history

### `GET` `/api/agent/{name}/network`

Get relationship network

### `GET` `/api/agent/{name}/rivals`

Get top rivals

### `GET` `/api/agent/{name}/allies`

Get top allies

### `GET` `/api/agent/{name}/moments`

Get significant moments

### `GET` `/api/agent/{name}/positions`

Get position history

### `GET` `/api/agent/{name}/metadata`

Get agent metadata (model, capabilities)

### `GET` `/api/agent/compare` 🔒

Compare multiple agents

### `GET` `/api/flips/recent`

Get recent flips across all agents

### `GET` `/api/flips/summary`

Get flip summary for dashboard

### `GET` `/api/flips/{flip_id}`

Get one detected flip

### `GET` `/api/matches/recent`

Get recent ELO matches

### `GET` `/api/matches/{match_id}`

Get one ELO match by its debate ID

---

## Calibration

Calibration endpoint handlers.

### `GET` `/api/agent/{name}/calibration-curve`

Get calibration curve (confidence vs accuracy)

### `GET` `/api/agent/{name}/calibration-summary`

Get calibration summary metrics

### `GET` `/api/calibration/leaderboard`

Get top agents by calibration score

---

## External Agents

External Agent Gateway endpoint handlers.

### `POST` `/api/external-agents/tasks`

Submit task to external agent

### `GET` `/api/external-agents/adapters`

List registered adapters

### `GET` `/api/external-agents/health`

Health check all adapters

---

## Feedback

Agent SelectionFeedbackLoop state API handler.

### `GET` `/api/v1/agents/feedback/metrics`

Loop metrics summary

### `GET` `/api/v1/agents/feedback/states`

Per-agent win rate, timeout rate, calibration

### `GET` `/api/v1/agents/{name}/feedback/domains`

Domain-specific weights

---

## Feedback Hub

Feedback Hub endpoint handlers.

### `GET` `/api/v1/feedback-hub/stats` 🔒

Routing statistics

### `GET` `/api/v1/feedback-hub/history` 🔒

Recent routing history

---

## Harnesses

External harness endpoint handlers.

### `GET` `/api/v1/harnesses` 🔒

List available harnesses

---

## Introspection

Introspection endpoint handlers.

### `GET` `/api/introspection/all`

Get introspection for all agents

### `GET` `/api/introspection/leaderboard`

Get agents ranked by reputation

### `GET` `/api/introspection/agents`

List available agents

### `GET` `/api/introspection/agents/{name}`

Get introspection for specific agent

---

## Laboratory

Persona laboratory endpoint handlers.

### `GET` `/api/laboratory/emergent-traits`

Get emergent traits from agent performance

---

## LeaderboardView

Handler for consolidated leaderboard view endpoint.

### `GET` `/api/leaderboard-view`

GET /api/leaderboard-view

---

## Persona

Persona-related endpoint handlers.

### `GET` `/api/personas`

Get all agent personas

### `GET` `/api/agent/{name}/persona`

Get agent persona

### `GET` `/api/agent/{name}/grounded-persona`

Get truth-grounded persona

### `GET` `/api/agent/{name}/identity-prompt` 🔒

Get identity prompt

### `GET` `/api/agent/{name}/performance`

Get agent performance summary

### `GET` `/api/agent/{name}/domains`

Get agent expertise domains

### `GET` `/api/agent/{name}/accuracy`

Get position accuracy stats

---

## Probes

Capability probing endpoint handlers.

### `POST` `/api/probes/capability` 🔒

Run capability probes on an agent to find vulnerabilities

---

## AgentRecommendation

Handler for agent recommendation and leaderboard endpoints.

### `GET` `/api/v1/agents/recommend`

Get top agent recommendations for a domain

### `GET` `/api/v1/agents/leaderboard`

Get agent leaderboard with optional domain filter

---

## Selection

Handler for selection plugin endpoints.

### `POST` `/api/v1/selection/plugins`

List all available selection plugins

### `POST` `/api/v1/selection/defaults`

Get default plugin configuration

### `POST` `/api/v1/selection/scorers`

List available scorer plugins

### `POST` `/api/v1/selection/team-selectors`

POST /api/v1/selection/team-selectors

### `POST` `/api/v1/selection/role-assigners`

POST /api/v1/selection/role-assigners

### `POST` `/api/v1/selection/score`

Get information about a specific scorer

### `POST` `/api/v1/selection/team`

Get information about a specific team selector

### `POST` `/api/v1/team-selection`

POST /api/v1/team-selection

### `POST` `/api/v1/agent-selection/plugins`

List all available selection plugins

### `POST` `/api/v1/agent-selection/defaults`

Get default plugin configuration

### `POST` `/api/v1/agent-selection/score`

Get information about a specific scorer

### `POST` `/api/v1/agent-selection/best`

POST /api/v1/agent-selection/best

### `POST` `/api/v1/agent-selection/select-team`

POST /api/v1/agent-selection/select-team

### `POST` `/api/v1/agent-selection/assign-roles`

POST /api/v1/agent-selection/assign-roles

### `POST` `/api/v1/agent-selection/history`

Get agent selection history

---

## Verticals

Vertical specialist endpoint handlers.

### `GET` `/api/verticals`

List available verticals

### `GET` `/api/verticals/:id`

Get vertical config

### `GET` `/api/verticals/:id/tools`

Get vertical tools

### `GET` `/api/verticals/:id/compliance`

Get compliance frameworks

### `GET` `/api/verticals/suggest`

Suggest vertical for a task

---

## AnalyticsPerformance

Handler for analytics performance endpoints.

### `GET` `/api/analytics/agents/performance`

Get aggregate agent performance metrics

### `GET` `/api/analytics/debates/summary`

Get debate summary statistics

### `GET` `/api/analytics/trends`

Calculate trend analysis from data points

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `data_points` | string | List of period data points |

---

## DecisionAnalytics

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

## ModerationAnalytics

Handler for moderation analytics dashboard endpoints.

### `GET` `/api/v1/moderation/stats`

Return moderation statistics

### `GET` `/api/v1/moderation/queue`

Return pending review items

---

## OutcomeAnalytics

Handler for decision outcome analytics endpoints.

### `GET` `/api/analytics/outcomes`

GET /api/analytics/outcomes/average-rounds

### `GET` `/api/analytics/outcomes/consensus-rate`

GET /api/analytics/outcomes/consensus-rate

### `GET` `/api/analytics/outcomes/average-rounds`

GET /api/analytics/outcomes/average-rounds

### `GET` `/api/analytics/outcomes/contributions`

GET /api/analytics/outcomes/contributions

### `GET` `/api/analytics/outcomes/quality-trend`

GET /api/analytics/outcomes/quality-trend

### `GET` `/api/analytics/outcomes/topics`

GET /api/analytics/outcomes/topics

---

## SpendAnalytics

Handler for spend analytics endpoints.

### `GET` `/api/v1/spend/analytics`

GET /api/v1/spend/analytics/anomalies

### `GET` `/api/v1/spend/analytics/trend`

GET /api/v1/spend/analytics/trend

### `GET` `/api/v1/spend/analytics/provider`

GET /api/v1/spend/analytics/provider

### `GET` `/api/v1/spend/analytics/agent`

GET /api/v1/spend/analytics/agent

### `GET` `/api/v1/spend/analytics/forecast`

GET /api/v1/spend/analytics/forecast

### `GET` `/api/v1/spend/analytics/anomalies`

GET /api/v1/spend/analytics/anomalies

---

## Agent Evolution Dashboard

Agent Evolution Dashboard API Handler.

### `GET` `/api/v1/agent-evolution/timeline`

Evolution events timeline

### `GET` `/api/v1/agent-evolution/elo-trends`

ELO score history per agent

### `GET` `/api/v1/agent-evolution/pending`

Pending Nomic Loop changes

### `POST` `/api/v1/agent-evolution/pending/{id}/approve`

Approve a pending change

### `POST` `/api/v1/agent-evolution/pending/{id}/reject`

Reject a pending change

---

## Dashboard

HTTP API Handlers for Dashboard.

### `GET` `/api/v1/dashboard/stats` 🔒

Get detailed stats

### `GET` `/api/v1/dashboard/activity` 🔒

Get recent activity

### `GET` `/api/v1/dashboard/inbox-summary` 🔒

Get inbox summary

### `GET` `/api/v1/dashboard/quick-actions` 🔒

Get available quick actions

### `POST` `/api/v1/dashboard/quick-actions/{action}` 🔒

Execute quick action

---

## Differentiation

Differentiation Dashboard Handler.

### `GET` `/api/v1/differentiation/summary`

Top-level differentiation metrics

### `GET` `/api/v1/differentiation/vetting`

Adversarial vetting evidence

### `GET` `/api/v1/differentiation/calibration`

Multi-agent calibration advantage

### `GET` `/api/v1/differentiation/memory`

Institutional memory growth

### `GET` `/api/v1/differentiation/benchmarks`

Industry benchmark comparison

---

## AnalyticsDashboard

Handler for analytics dashboard endpoints.

### `GET` `/api/analytics/summary`

GET /api/analytics/summary

### `GET` `/api/analytics/trends/findings`

GET /api/analytics/trends/findings

### `GET` `/api/analytics/remediation`

GET /api/analytics/remediation

### `GET` `/api/analytics/agents`

GET /api/analytics/agents

### `GET` `/api/analytics/cost`

GET /api/analytics/cost

### `GET` `/api/analytics/compliance`

GET /api/analytics/compliance

### `GET` `/api/analytics/heatmap`

GET /api/analytics/heatmap

### `GET` `/api/analytics/tokens`

GET /api/analytics/tokens

### `GET` `/api/analytics/tokens/trends`

GET /api/analytics/tokens/trends

### `GET` `/api/analytics/tokens/providers`

GET /api/analytics/tokens/providers

### `GET` `/api/analytics/cost/breakdown`

GET /api/analytics/cost/breakdown

### `GET` `/api/analytics/flips/summary`

GET /api/analytics/flips/summary

### `GET` `/api/analytics/flips/recent`

GET /api/analytics/flips/recent

### `GET` `/api/analytics/flips/consistency`

GET /api/analytics/flips/consistency

### `GET` `/api/analytics/flips/trends`

GET /api/analytics/flips/trends

### `GET` `/api/analytics/deliberations`

GET /api/analytics/deliberations

### `GET` `/api/analytics/deliberations/channels`

GET /api/analytics/deliberations/channels

### `GET` `/api/analytics/deliberations/consensus`

GET /api/analytics/deliberations/consensus

### `GET` `/api/analytics/deliberations/performance`

GET /api/analytics/deliberations/performance

---

## Outcome Dashboard

Decision Outcome Dashboard API Handler.

### `GET` `/api/v1/outcome-dashboard`

Full dashboard data

### `GET` `/api/v1/outcome-dashboard/quality`

Decision quality score + trend

### `GET` `/api/v1/outcome-dashboard/agents`

Agent leaderboard (ELO + Brier)

### `GET` `/api/v1/outcome-dashboard/history`

Decision history with scores

### `GET` `/api/v1/outcome-dashboard/calibration`

Calibration curve data

---

## Handler

User Authentication Handler.

### `POST` `/api/auth/register`

Create a new user account

### `POST` `/api/auth/login`

Authenticate and get tokens

### `POST` `/api/auth/logout` 🔒

Invalidate current token (adds to blacklist)

### `POST` `/api/auth/logout-all` 🔒

Invalidate all tokens for user (logout all devices)

### `POST` `/api/auth/refresh`

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

### `POST` `/api/auth/mfa` 🔒

Compatibility MFA action endpoint

### `GET` `/api/auth/sessions` 🔒

List active sessions for current user

### `DELETE` `/api/auth/sessions/:id` 🔒

Revoke a specific session

---

## RBAC

HTTP handler for RBAC management endpoints.

### `GET` `/api/v1/rbac/permissions`

List all system permissions with optional filtering

### `GET` `/api/v1/rbac/roles`

List all roles (system and custom)

### `GET` `/api/v1/rbac/assignments`

List role assignments with optional filtering

### `GET` `/api/v1/rbac/check`

Check if a user has a specific permission

---

## SCIM

HTTP request handler for SCIM 2.0 provisioning endpoints.

### `GET` `/scim/v2/Users`

Extract resource ID from path like /scim/v2/Users/{id}

### `POST` `/scim/v2/Users`

Extract resource ID from path like /scim/v2/Users/{id}

### `GET` `/scim/v2/Groups`

GET /scim/v2/Groups

### `POST` `/scim/v2/Groups`

POST /scim/v2/Groups

---

## Signup Handlers

HTTP API Handlers for Self-Service Signup.

### `POST` `/api/v1/auth/verify-email`

Verify email address

### `POST` `/api/v1/auth/resend-verification`

Resend verification email

### `POST` `/api/v1/auth/setup-organization` 🔒

Create organization after signup

### `POST` `/api/v1/auth/invite` 🔒

Invite team member

### `POST` `/api/v1/auth/accept-invite`

Accept team invitation

### `GET` `/api/v1/auth/check-invite`

Check invitation validity

---

## SSO

Handler for SSO (Single Sign-On) endpoints.

### `GET` `/auth/sso/login`

GET /auth/sso/login

### `POST` `/auth/sso/login` 🔒

POST /auth/sso/login

### `GET` `/auth/sso/callback`

GET /auth/sso/callback

### `POST` `/auth/sso/callback` 🔒

POST /auth/sso/callback

### `GET` `/auth/sso/logout`

GET /auth/sso/logout

### `POST` `/auth/sso/logout` 🔒

POST /auth/sso/logout

### `GET` `/auth/sso/metadata`

GET /auth/sso/metadata

### `GET` `/auth/sso/status`

GET /auth/sso/status

### `GET` `/api/v2/sso/login`

GET /api/v2/sso/login

### `POST` `/api/v2/sso/login` 🔒

POST /api/v2/sso/login

### `GET` `/api/v2/sso/callback`

GET /api/v2/sso/callback

### `POST` `/api/v2/sso/callback` 🔒

POST /api/v2/sso/callback

### `GET` `/api/v2/sso/logout`

GET /api/v2/sso/logout

### `POST` `/api/v2/sso/logout` 🔒

POST /api/v2/sso/logout

### `GET` `/api/v2/sso/status`

GET /api/v2/sso/status

### `GET` `/api/v2/sso/metadata`

GET /api/v2/sso/metadata

---

## Autonomous Learning

Autonomous Learning Handler for Aragora.

### `POST` `/api/v2/learning/sessions`

Start new training session

### `GET` `/api/v2/learning/sessions/:session_id` 🔒

Get session details

### `GET` `/api/v2/learning/metrics/:metric_type` 🔒

Get specific metric

### `POST` `/api/v2/learning/feedback`

Submit learning feedback

### `POST` `/api/v2/learning/calibrate`

Trigger calibration

---

## Gastown Dashboard

Gas Town Dashboard API Handlers.

### `GET` `/api/v1/dashboard/gastown/overview`

Get Gas Town overview

### `GET` `/api/v1/dashboard/gastown/convoys`

Get convoy list with progress

### `GET` `/api/v1/dashboard/gastown/agents`

Get agent workload distribution

### `GET` `/api/v1/dashboard/gastown/beads`

Get bead queue stats

### `GET` `/api/v1/dashboard/gastown/metrics`

Get throughput metrics

---

## Monitoring

HTTP handlers for monitoring operations.

### `GET` `/api/v1/autonomous/monitoring/record`

GET /api/v1/autonomous/monitoring/record

### `GET` `/api/v1/autonomous/monitoring/trends`

GET /api/v1/autonomous/monitoring/trends

### `GET` `/api/v1/autonomous/monitoring/anomalies`

GET /api/v1/autonomous/monitoring/anomalies

### `GET` `/api/v1/autonomous/monitoring/baseline`

GET /api/v1/autonomous/monitoring/baseline

### `GET` `/api/v1/autonomous/monitoring/circuit-breaker`

GET /api/v1/autonomous/monitoring/circuit-breaker

---

## Nomic

Nomic loop state and monitoring endpoint handlers.

### `GET` `/api/nomic/state`

Get nomic loop state

### `GET` `/api/nomic/health`

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

### `GET` `/api/modes`

Get available operational modes

---

## RalphDashboard

Handler for Ralph campaign dashboard endpoints.

### `GET` `/api/ralph/campaigns` 🔒

GET /api/ralph/campaigns

### `GET` `/api/ralph/campaigns/{campaign_id}` 🔒

GET /api/ralph/campaigns/{campaign_id}

### `GET` `/api/ralph/campaigns/{campaign_id}/timeline` 🔒

GET /api/ralph/campaigns/{campaign_id}/timeline

### `GET` `/api/ralph/campaigns/{campaign_id}/blockers` 🔒

GET /api/ralph/campaigns/{campaign_id}/blockers

### `GET` `/api/ralph/campaigns/{campaign_id}/repairs` 🔒

GET /api/ralph/campaigns/{campaign_id}/repairs

### `GET` `/api/ralph/campaigns/{campaign_id}/budget` 🔒

GET /api/ralph/campaigns/{campaign_id}/budget

### `GET` `/api/ralph/campaigns/{campaign_id}/pr-gate` 🔒

GET /api/ralph/campaigns/{campaign_id}/pr-gate

### `GET` `/api/ralph/overview` 🔒

GET /api/ralph/overview

### `GET` `/api/ralph/blockers` 🔒

GET /api/ralph/blockers

---

## Self Improve

Self-improvement run management endpoints.

### `POST` `/api/self-improve/run`

Start a new self-improvement cycle

### `POST` `/api/self-improve/start`

Start a new run (legacy alias)

### `POST` `/api/self-improve/runs/:id/cancel`

Cancel a running run

### `POST` `/api/self-improve/coordinate`

Start a hierarchical coordination cycle

### `POST` `/api/self-improve/worktrees/cleanup`

Clean up all worktrees

### `POST` `/api/self-improve/worktrees/autopilot/ensure`

Ensure managed autopilot worktree

### `POST` `/api/self-improve/worktrees/autopilot/reconcile`

Reconcile managed autopilot sessions

### `POST` `/api/self-improve/worktrees/autopilot/cleanup`

Cleanup managed autopilot sessions

### `POST` `/api/self-improve/worktrees/autopilot/maintain`

Run autopilot maintain lifecycle

---

## Self Improve Details

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

### `PUT` `/api/self-improve/improvement-queue/{id}/priority` 🔒

Reorder queue items

### `DELETE` `/api/self-improve/improvement-queue/{id}` 🔒

Remove queue items

---

## Budgets

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

### `GET` `/api/v1/budgets/trends`

Get org-wide spending trends

### `POST` `/api/v1/budgets/check` 🔒

Pre-flight cost check

---

## CostDashboard

Handler for the consolidated cost dashboard endpoint.

### `GET` `/api/v1/billing/dashboard`

Get the consolidated cost dashboard summary

---

## UsageMetering

Handler for usage metering endpoints.

### `GET` `/api/v1/billing/usage`

Export usage data as CSV

### `GET` `/api/v1/billing/usage/breakdown`

Get detailed usage breakdown for billing

### `GET` `/api/v1/billing/limits`

Get current usage limits and utilization percentages

### `GET` `/api/v1/billing/usage/summary`

GET /api/v1/billing/usage/summary

### `GET` `/api/v1/billing/usage/export`

Export usage data as CSV

### `GET` `/api/v1/quotas`

GET /api/v1/quotas

---

## UsageMetering

Handler for usage metering endpoints.

### `GET` `/api/v1/billing/usage`

Export usage data as CSV

### `GET` `/api/v1/billing/usage/breakdown`

Get detailed usage breakdown for billing

### `GET` `/api/v1/billing/usage/summary`

GET /api/v1/billing/usage/summary

### `GET` `/api/v1/billing/usage/export`

Export usage data as CSV

### `GET` `/api/v1/billing/limits`

Get current usage limits and utilization percentages

### `GET` `/api/v1/quotas`

GET /api/v1/quotas

### `GET` `/api/v1/quotas/usage`

Export usage data as CSV

---

## Email Webhook

Email Webhook Handler for Inbound Email Processing.

### `POST` `/api/v1/bots/email/webhook/sendgrid`

SendGrid Inbound Parse

### `POST` `/api/v1/bots/email/webhook/mailgun` 🔒

Mailgun Inbound Webhook

### `POST` `/api/v1/bots/email/webhook/ses`

AWS SES SNS notifications

### `GET` `/api/v1/bots/email/status` 🔒

Integration status

---

## Slack

Handler for Slack bot integration endpoints.

### `GET` `/api/v1/bots/slack/status` 🔒

Return system status for Slack

### `POST` `/api/v1/bots/slack/events`

POST /api/v1/bots/slack/events

### `POST` `/api/v1/bots/slack/interactions`

POST /api/v1/bots/slack/interactions

### `POST` `/api/v1/bots/slack/commands`

POST /api/v1/bots/slack/commands

---

## Handler

Microsoft Teams Bot main handler.

### `POST` `/api/v1/bots/teams/messages`

Handle incoming Bot Framework activities

### `GET` `/api/v1/bots/teams/status`

Bot status

---

## IdeaCanvas

Handler for Idea Canvas REST API endpoints.

### `GET` `/api/v1/ideas`

GET /api/v1/ideas

---

## Marketplace

Marketplace API Handlers.

### `GET` `/api/v1/marketplace/templates`

List all templates

### `GET` `/api/v1/marketplace/templates/{id}`

Get template details

### `GET` `/api/v1/marketplace/categories`

List categories

### `GET` `/api/v1/marketplace/status`

Health and circuit breaker status

---

## MarketplaceBrowse

Handler for marketplace template browsing endpoints.

### `GET` `/api/v1/marketplace/templates`

GET /api/v1/marketplace/templates

### `GET` `/api/v1/marketplace/featured`

Return featured templates

### `GET` `/api/v1/marketplace/popular`

Return popular templates sorted by downloads

---

## Marketplace Pilot

Marketplace Pilot API Handler.

### `GET` `/api/v1/marketplace/listings` 🔒

Browse listings with filters

### `GET` `/api/v1/marketplace/listings/featured` 🔒

Featured listings

### `GET` `/api/v1/marketplace/listings/stats` 🔒

Marketplace statistics

### `GET` `/api/v1/marketplace/listings/{id}` 🔒

Get listing details

### `POST` `/api/v1/marketplace/listings/{id}/install` 🔒

Install a listing

### `POST` `/api/v1/marketplace/listings/{id}/rate` 🔒

Rate a listing

### `POST` `/api/v1/marketplace/listings/{id}/launch-debate` 🔒

Launch debate from listing

---

## Playbook

Handler for playbook API endpoints.

### `GET` `/api/playbooks`

Extract playbook ID from a path like /api/playbooks/{id}[/run]

---

## Skill Marketplace

Skill Marketplace API Handlers.

### `GET` `/api/v1/skills/marketplace/search`

Search skills

### `GET` `/api/v1/skills/marketplace/installed`

List installed skills

### `GET` `/api/v1/skills/marketplace/stats`

Get marketplace statistics

---

## Skills

Skills endpoint handlers.

### `GET` `/api/skills`

List all registered skills

### `POST` `/api/skills/invoke`

Invoke a skill by name

### `GET` `/api/skills/:name/metrics`

Get skill execution metrics

---

## TemplateDiscovery

Handler for template discovery endpoints.

### `GET` `/api/v1/templates`

GET /api/v1/templates

### `GET` `/api/v1/templates/categories`

Return categories with counts

### `GET` `/api/v1/templates/recommend`

Recommend templates for a given question

---

## Workflow Templates

Workflow Templates API Handler.

### `GET` `/api/workflow/templates`

List available templates

### `GET` `/api/workflow/templates/:id`

Get template details

### `GET` `/api/workflow/templates/:id/package`

Get full package

---

## Code Review

HTTP API Handlers for Code Review.

### `POST` `/api/v1/code-review/review`

Review code snippet

### `POST` `/api/v1/code-review/diff`

Review diff/patch

### `POST` `/api/v1/code-review/pr`

Review GitHub PR

### `GET` `/api/v1/code-review/results/{id}`

Get review results

### `GET` `/api/v1/code-review/history`

Get review history

---

## Dependency Analysis

HTTP API Handlers for Dependency Analysis.

### `POST` `/api/v1/codebase/analyze-dependencies` 🔒

Analyze project dependencies

### `POST` `/api/v1/codebase/scan-vulnerabilities` 🔒

Scan for CVEs

### `POST` `/api/v1/codebase/check-licenses` 🔒

Check license compatibility

---

## Intelligence

HTTP API Handlers for Code Intelligence Analysis.

### `POST` `/api/v1/codebase/{repo}/analyze` 🔒

Analyze codebase structure

### `GET` `/api/v1/codebase/{repo}/symbols` 🔒

List symbols (classes, functions)

### `GET` `/api/v1/codebase/{repo}/callgraph` 🔒

Get call graph

### `GET` `/api/v1/codebase/{repo}/deadcode` 🔒

Find dead/unreachable code

### `POST` `/api/v1/codebase/{repo}/impact` 🔒

Analyze impact of changes

### `POST` `/api/v1/codebase/{repo}/understand` 🔒

Answer questions about code

### `POST` `/api/v1/codebase/{repo}/audit` 🔒

Run comprehensive audit

---

## Metrics

HTTP API Handlers for Codebase Metrics Analysis.

### `POST` `/api/v1/codebase/{repo}/metrics/analyze` 🔒

Run metrics analysis

### `GET` `/api/v1/codebase/{repo}/metrics` 🔒

Get latest metrics

### `GET` `/api/v1/codebase/{repo}/metrics/{analysis_id}` 🔒

Get specific analysis

### `GET` `/api/v1/codebase/{repo}/hotspots` 🔒

Get complexity hotspots

### `GET` `/api/v1/codebase/{repo}/duplicates` 🔒

Get code duplicates

---

## Quick Scan

Quick Security Scan API Handler.

### `POST` `/api/codebase/quick-scan` 🔒

Run quick security scan

### `GET` `/api/codebase/quick-scan/{scan_id}` 🔒

Get scan result

---

## Reviews

Reviews Handler - Serve shareable code reviews.

### `GET` `/api/reviews`

List recent reviews

---

## Audit Trail

Audit Trail HTTP Handlers for Aragora.

### `GET` `/api/v1/audit-trails`

List recent audit trails

### `GET` `/api/v1/receipts`

List recent decision receipts

---

## Data Classification Handler

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

## Compliance

HTTP handler for compliance and audit operations.

### `GET` `/api/v1/compliance/rbac-coverage`

GET /api/v1/compliance/rbac-coverage  Returns RBAC endpoint coverage metrics

### `GET` `/api/v2/compliance` 🔒

GET /api/v2/compliance

---

## Queue

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

---

## Cost

Handler for cost visibility API endpoints.

### `GET` `/api/v1/costs` 🔒

GET /api/v1/costs

### `GET` `/api/v1/costs/alerts` 🔒

GET /api/v1/costs/alerts

### `POST` `/api/v1/costs/alerts` 🔒

POST /api/v1/costs/alerts

### `GET` `/api/v1/costs/analytics/budget-utilization` 🔒

GET /api/v1/costs/analytics/budget-utilization

### `POST` `/api/v1/costs/analytics/budget-utilization`

POST /api/v1/costs/analytics/budget-utilization

### `GET` `/api/v1/costs/analytics/by-agent` 🔒

GET /api/v1/costs/analytics/by-agent

### `POST` `/api/v1/costs/analytics/by-agent`

POST /api/v1/costs/analytics/by-agent

### `GET` `/api/v1/costs/analytics/by-debate` 🔒

GET /api/v1/costs/analytics/by-debate

### `POST` `/api/v1/costs/analytics/by-debate`

POST /api/v1/costs/analytics/by-debate

### `GET` `/api/v1/costs/analytics/by-model` 🔒

GET /api/v1/costs/analytics/by-model

### `POST` `/api/v1/costs/analytics/by-model`

POST /api/v1/costs/analytics/by-model

### `GET` `/api/v1/costs/analytics/trend` 🔒

GET /api/v1/costs/analytics/trend

### `POST` `/api/v1/costs/analytics/trend`

POST /api/v1/costs/analytics/trend

### `GET` `/api/v1/costs/breakdown` 🔒

GET /api/v1/costs/breakdown

### `POST` `/api/v1/costs/budget` 🔒

POST /api/v1/costs/budget

### `GET` `/api/v1/costs/budgets` 🔒

GET /api/v1/costs/budgets

### `POST` `/api/v1/costs/budgets` 🔒

POST /api/v1/costs/budgets

### `POST` `/api/v1/costs/constraints/check` 🔒

POST /api/v1/costs/constraints/check

### `GET` `/api/v1/costs/efficiency` 🔒

GET /api/v1/costs/efficiency

### `POST` `/api/v1/costs/estimate` 🔒

POST /api/v1/costs/estimate

### `GET` `/api/v1/costs/export` 🔒

GET /api/v1/costs/export

### `GET` `/api/v1/costs/forecast` 🔒

GET /api/v1/costs/forecast

### `GET` `/api/v1/costs/forecast/detailed` 🔒

GET /api/v1/costs/forecast/detailed

### `POST` `/api/v1/costs/forecast/simulate`

POST /api/v1/costs/forecast/simulate

### `GET` `/api/v1/costs/recommendations` 🔒

GET /api/v1/costs/recommendations

### `GET` `/api/v1/costs/recommendations/detailed` 🔒

GET /api/v1/costs/recommendations/detailed

### `GET` `/api/v1/costs/timeline` 🔒

GET /api/v1/costs/timeline

### `GET` `/api/v1/costs/usage` 🔒

GET /api/v1/costs/usage

### `GET` `/api/v1/costs/debates/{debate_id}` 🔒

GET /api/v1/costs/debates/{debate_id}

### `GET` `/api/v1/costs/debates/{debate_id}/line-items` 🔒

GET /api/v1/costs/debates/{debate_id}/line-items

### `GET` `/api/v1/costs/debates/{debate_id}/performance` 🔒

GET /api/v1/costs/debates/{debate_id}/performance

### `GET` `/api/costs` 🔒

GET /api/costs

### `GET` `/api/costs/alerts` 🔒

GET /api/costs/alerts

### `POST` `/api/costs/alerts` 🔒

POST /api/costs/alerts

### `POST` `/api/costs/analytics/budget-utilization`

POST /api/costs/analytics/budget-utilization

### `POST` `/api/costs/analytics/by-agent`

POST /api/costs/analytics/by-agent

### `POST` `/api/costs/analytics/by-debate`

POST /api/costs/analytics/by-debate

### `POST` `/api/costs/analytics/by-model`

POST /api/costs/analytics/by-model

### `POST` `/api/costs/analytics/trend`

POST /api/costs/analytics/trend

### `GET` `/api/costs/breakdown` 🔒

GET /api/costs/breakdown

### `POST` `/api/costs/budget` 🔒

POST /api/costs/budget

### `GET` `/api/costs/budgets` 🔒

GET /api/costs/budgets

### `POST` `/api/costs/budgets`

POST /api/costs/budgets

### `POST` `/api/costs/constraints/check`

POST /api/costs/constraints/check

### `GET` `/api/costs/efficiency` 🔒

GET /api/costs/efficiency

### `POST` `/api/costs/estimate`

POST /api/costs/estimate

### `GET` `/api/costs/export` 🔒

GET /api/costs/export

### `GET` `/api/costs/forecast` 🔒

GET /api/costs/forecast

### `GET` `/api/costs/forecast/detailed` 🔒

GET /api/costs/forecast/detailed

### `POST` `/api/costs/forecast/simulate`

POST /api/costs/forecast/simulate

### `GET` `/api/costs/recommendations` 🔒

GET /api/costs/recommendations

### `GET` `/api/costs/recommendations/detailed` 🔒

GET /api/costs/recommendations/detailed

### `GET` `/api/costs/timeline` 🔒

GET /api/costs/timeline

### `GET` `/api/costs/usage` 🔒

GET /api/costs/usage

### `GET` `/api/costs/debates/{debate_id}` 🔒

GET /api/costs/debates/{debate_id}

### `GET` `/api/costs/debates/{debate_id}/line-items` 🔒

GET /api/costs/debates/{debate_id}/line-items

### `GET` `/api/costs/debates/{debate_id}/performance` 🔒

GET /api/costs/debates/{debate_id}/performance

---

## Audience Suggestions

Audience suggestion handler for debate audience input.

### `GET` `/api/v1/audience/suggestions`

List clustered suggestions for a debate

---

## Auditing

Auditing and security analysis endpoint handlers.

### `POST` `/api/debates/capability-probe` 🔒

Run capability probes on an agent

### `POST` `/api/debates/deep-audit` 🔒

Run deep audit on a task

---

## Belief

Belief Network and Reasoning endpoint handlers.

### `GET` `/api/belief-network/:debate_id/cruxes` 🔒

Get key claims that impact debate outcome

### `GET` `/api/belief-network/:debate_id/load-bearing-claims` 🔒

Get high-centrality claims

### `GET` `/api/provenance/:debate_id/claims/:claim_id/support`

Get claim verification status

### `GET` `/api/laboratory/emergent-traits`

Get emergent traits from agent performance

### `GET` `/api/debate/:debate_id/graph-stats` 🔒

Get argument graph statistics

---

## DebateDecisionBridge

POST handler for bridging a debate's latest DecisionPlan to external tools.

### `POST` `/api/v1/debates/{id}/bridge` 🔒

POST /api/v1/debates/{id}/bridge

---

## Composite

Composite API handlers that aggregate data from multiple subsystems.

### `GET` `/api/v1/debates/{id}/full-context`

Memory + Knowledge + Belief context

### `GET` `/api/v1/agents/{id}/reliability`

Circuit breaker + Airlock metrics

### `GET` `/api/v1/debates/{id}/compression-analysis`

RLM compression metrics

---

## Context Budget

Context budget handler for managing debate prompt token budgets.

### `GET` `/api/v1/context/budget`

Get current context budget configuration

---

## Critique

Critique pattern and reputation endpoint handlers.

### `GET` `/api/critiques/patterns`

Get high-impact critique patterns

### `GET` `/api/critiques/archive`

Get archive statistics

### `GET` `/api/reputation/all`

Get all agent reputations

### `GET` `/api/reputation/:name`

Get specific agent reputation

### `GET` `/api/agent/:name/reputation`

Get specific agent reputation

---

## Debate Intervention

Debate intervention and reasoning endpoint handlers.

### `POST` `/api/v1/debates/{debate_id}/intervene`

Submit a mid-debate intervention

---

## Debate Stats

Debate statistics handler for aggregate debate metrics.

### `GET` `/api/v1/debates/stats`

Get aggregate debate statistics

### `GET` `/api/v1/debates/stats/agents`

Get per-agent statistics

---

## Deliberations

Handler for vetted decisionmaking dashboard endpoints.

### `GET` `/api/v1/deliberations/active` 🔒

Fetch active vetted decisionmaking sessions from the debate store

### `GET` `/api/v1/deliberations/stats` 🔒

Get deliberation statistics

### `GET` `/api/v1/deliberations/stream` 🔒

Handle WebSocket stream for real-time updates

### `GET` `/api/v1/deliberations/{deliberation_id}` 🔒

GET /api/v1/deliberations/{deliberation_id}

---

## Handler

Debate-related endpoint handlers.

### `GET` `/api/debates` 🔒

List all debates

### `GET` `/api/debates/{slug}` 🔒

Get debate by slug

### `GET` `/api/debates/slug/{slug}`

Get debate by slug (alternative)

### `GET` `/api/debates/{id}/export/{format}`

Export debate

### `GET` `/api/debates/{id}/impasse`

Detect debate impasse

### `GET` `/api/debates/{id}/convergence`

Get convergence status

### `GET` `/api/debates/{id}/citations`

Get evidence citations for debate

### `GET` `/api/debates/{id}/evidence`

Get comprehensive evidence trail

### `POST` `/api/debates/{id}/fork`

Fork debate at a branch point

### `PATCH` `/api/debates/{id}` 🔒

Update debate metadata (title, tags, status)

### `DELETE` `/api/debates/{id}` 🔒

Permanently delete a debate (cascades to critiques)

### `GET` `/api/search`

Cross-debate search by query

---

## HybridDebate

HTTP request handler for hybrid debate API endpoints.

### `GET` `/api/v1/debates/hybrid` 🔒

Handle POST /api/v1/debates/hybrid

### `POST` `/api/v1/debates/hybrid` 🔒

Handle POST /api/v1/debates/hybrid

---

## Moments

Moments endpoint handlers.

### `GET` `/api/moments/summary`

Global moments overview

### `GET` `/api/moments/timeline`

Chronological moments (limit, offset)

### `GET` `/api/moments/by-type/{type}`

Filter moments by type

### `GET` `/api/moments/trending`

Most significant recent moments

---

## Tournaments

Tournament-related endpoint handlers.

### `GET` `/api/tournaments`

List all tournaments

### `GET` `/api/tournaments/{id}/standings`

Get tournament standings

### `POST` `/api/tournaments/{id}/advance`

Advance to next round

### `POST` `/api/tournaments/{id}/matches/{match_id}/result`

Record match result

---

## Decision

Handler for unified decision-making API endpoints.

### `GET` `/api/v1/decisions` 🔒

List recent decisions

### `POST` `/api/v1/decisions` 🔒

List recent decisions

---

## Explainability

Handler for debate explainability endpoints.

### `GET` `/api/v1/explain`

GET /api/v1/explain

### `POST` `/api/v1/explainability/batch`

Create a new batch explainability job

### `GET` `/api/v1/explainability/compare`

Compare explanations between multiple debates

---

## Pipeline

Decision Pipeline HTTP handlers.

### `POST` `/api/v1/decisions/plans`

Create plan from debate result

### `GET` `/api/v1/decisions/plans/{plan_id}` 🔒

Get plan details

### `POST` `/api/v1/decisions/plans/{plan_id}/approve`

Approve plan

### `POST` `/api/v1/decisions/plans/{plan_id}/reject`

Reject plan

### `POST` `/api/v1/decisions/plans/{plan_id}/execute`

Execute approved plan

---

## Receipts

Decision Receipt HTTP Handlers for Aragora.

### `GET` `/api/v2/receipts` 🔒

List receipts with filters

### `GET` `/api/v2/receipts/search` 🔒

Full-text search receipts

### `GET` `/api/v2/receipts/:receipt_id` 🔒

Get specific receipt

### `GET` `/api/v2/receipts/:receipt_id/export` 🔒

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

### `GET` `/api/v2/receipts/share/:token`

Access receipt via share token

### `GET` `/api/v2/receipts/signing-key`

ODR signing public key (JSON envelope)

### `GET` `/.well-known/aragora-odr-signing-key`

ODR signing public key (raw PEM)

### `GET` `/api/v1/receipts/deliveries` 🔒

Legacy/frontend delivery history bridge

---

## Playground

HTTP handler for the public playground demo.

### `POST` `/api/v1/playground/assess`

Assess question ambiguity using a frontier model

### `POST` `/api/v1/playground/debate`

Retrieve a saved debate by ID for shareable links

### `POST` `/api/v1/playground/debate/live`

Run a live debate with real API-backed agents

### `POST` `/api/v1/playground/debate/live/cost-estimate`

POST /api/v1/playground/debate/live/cost-estimate

### `POST` `/api/v1/playground/landing/events`

POST /api/v1/playground/landing/events

### `GET` `/api/v1/playground/landing/events/summary`

Summarize recent landing telemetry without exposing raw events

### `GET` `/api/v1/playground/landing/feedback` 🔒

Accept a bounded wrong-answer report from the landing page

### `POST` `/api/v1/playground/landing/feedback`

Accept a bounded wrong-answer report from the landing page

### `POST` `/api/v1/playground/landing/feedback/review` 🔒

Update admin review state for a wrong-answer report

### `POST` `/api/v1/playground/status`

POST /api/v1/playground/status

### `POST` `/api/v1/playground/tts`

Proxy text-to-speech through ElevenLabs, returning audio/mpeg

---

## EmailDebate

Handler for email vetted decisionmaking API endpoints.

### `GET` `/api/v1/email/prioritize`

Prioritize multiple emails

### `POST` `/api/v1/email/prioritize` 🔒

Prioritize multiple emails

### `POST` `/api/v1/email/prioritize/batch`

Prioritize multiple emails

### `POST` `/api/v1/email/triage`

Full inbox triage with categorization and sorting

---

## Email Services

HTTP API Handlers for Email Services.

### `POST` `/api/v1/email/followups/mark`

Mark email as awaiting reply

### `GET` `/api/v1/email/followups/pending`

List pending follow-ups

### `POST` `/api/v1/email/followups/check-replies`

Check for replies

### `GET` `/api/v1/email/snoozed`

List snoozed emails

### `GET` `/api/v1/email/categories`

List available categories

### `POST` `/api/v1/email/categories/learn`

Category feedback (501: learning is not implemented)

---

## EmailTriage

Handler for email triage rules management.

### `GET` `/api/v1/email/triage/rules`

Return current triage rules

### `PUT` `/api/v1/email/triage/rules`

Return current triage rules

### `POST` `/api/v1/email/triage/test`

Test a message against current triage rules

---

## Email

HTTP handler for email prioritization endpoints.

### `GET` `/api/v1/email/prioritize`

GET /api/v1/email/prioritize

### `POST` `/api/v1/email/prioritize` 🔒

POST /api/v1/email/prioritize

### `GET` `/api/v1/email/rank-inbox`

GET /api/v1/email/rank-inbox

### `POST` `/api/v1/email/rank-inbox` 🔒

POST /api/v1/email/rank-inbox

### `GET` `/api/v1/email/feedback`

GET /api/v1/email/feedback

### `POST` `/api/v1/email/feedback` 🔒

POST /api/v1/email/feedback

### `GET` `/api/v1/email/feedback/batch`

GET /api/v1/email/feedback/batch

### `POST` `/api/v1/email/feedback/batch` 🔒

POST /api/v1/email/feedback/batch

### `GET` `/api/v1/email/inbox`

GET /api/v1/email/inbox

### `GET` `/api/v1/email/config`

GET /api/v1/email/config

### `PUT` `/api/v1/email/config` 🔒

PUT /api/v1/email/config

### `GET` `/api/v1/email/vip`

GET /api/v1/email/vip

### `POST` `/api/v1/email/vip` 🔒

POST /api/v1/email/vip

### `DELETE` `/api/v1/email/vip` 🔒

DELETE /api/v1/email/vip

### `GET` `/api/v1/email/categorize`

GET /api/v1/email/categorize

### `POST` `/api/v1/email/categorize` 🔒

POST /api/v1/email/categorize

### `GET` `/api/v1/email/categorize/batch`

GET /api/v1/email/categorize/batch

### `POST` `/api/v1/email/categorize/batch` 🔒

POST /api/v1/email/categorize/batch

### `GET` `/api/v1/email/categorize/apply-label`

GET /api/v1/email/categorize/apply-label

### `POST` `/api/v1/email/categorize/apply-label` 🔒

POST /api/v1/email/categorize/apply-label

### `GET` `/api/v1/email/gmail/oauth/url`

GET /api/v1/email/gmail/oauth/url

### `POST` `/api/v1/email/gmail/oauth/url` 🔒

POST /api/v1/email/gmail/oauth/url

### `GET` `/api/v1/email/gmail/oauth/callback`

GET /api/v1/email/gmail/oauth/callback

### `POST` `/api/v1/email/gmail/oauth/callback` 🔒

POST /api/v1/email/gmail/oauth/callback

### `GET` `/api/v1/email/gmail/status`

GET /api/v1/email/gmail/status

### `GET` `/api/v1/email/context/boost`

GET /api/v1/email/context/boost

### `POST` `/api/v1/email/context/boost` 🔒

POST /api/v1/email/context/boost

---

## Ab Testing

Evolution A/B testing endpoint handlers.

### `GET` `/api/evolution/ab-tests`

List all A/B tests

### `POST` `/api/evolution/ab-tests`

Start new A/B test

---

## Cross Pollination

Cross-Pollination observability endpoint handlers.

### `GET` `/api/cross-pollination/stats`

Get cross-subscriber statistics

### `GET` `/api/cross-pollination/subscribers`

List all subscribers

### `GET` `/api/cross-pollination/bridge`

Arena event bridge status

### `POST` `/api/cross-pollination/reset`

Reset subscriber statistics

---

## Genesis

Genesis (evolution visibility) endpoint handlers.

### `GET` `/api/genesis/stats`

Get overall genesis statistics

### `GET` `/api/genesis/events`

Get recent genesis events

### `GET` `/api/genesis/lineage/:genome_id`

Get genome ancestry

### `GET` `/api/genesis/tree/:debate_id`

Get debate tree structure

### `GET` `/api/genesis/genomes`

List all genomes

### `GET` `/api/genesis/genomes/top`

Get top genomes by fitness

---

## Handler

Prompt evolution endpoint handlers.

### `GET` `/api/evolution/patterns`

Get top patterns across all agents

### `GET` `/api/evolution/summary`

Get evolution summary statistics

### `GET` `/api/evolution/{agent}/history`

Get prompt evolution history for an agent

### `GET` `/api/evolution/{agent}/prompt`

Get current/specific prompt version for an agent

---

## Replays

Replays and learning evolution endpoint handlers.

### `GET` `/api/replays`

List available replays

### `GET` `/api/replays/:replay_id`

Get specific replay with events

### `GET` `/api/learning/evolution`

Get meta-learning patterns

### `GET` `/api/meta-learning/stats`

Get meta-learning hyperparameters and efficiency stats

---

## Training

Handler for training data export endpoints.

### `GET` `/api/training/export/sft`

Get or create SFT exporter

### `GET` `/api/training/export/dpo`

Get or create DPO exporter

### `GET` `/api/training/export/gauntlet`

Get or create Gauntlet exporter

### `GET` `/api/training/stats`

GET /api/training/stats

### `GET` `/api/training/formats`

GET /api/training/formats

### `GET` `/api/training/jobs`

GET /api/training/jobs

### `GET` `/api/v1/training/export/sft`

Get or create SFT exporter

### `GET` `/api/v1/training/export/dpo`

Get or create DPO exporter

### `GET` `/api/v1/training/export/gauntlet`

Get or create Gauntlet exporter

### `GET` `/api/v1/training/stats`

GET /api/v1/training/stats

### `GET` `/api/v1/training/formats`

GET /api/v1/training/formats

### `GET` `/api/v1/training/jobs`

GET /api/v1/training/jobs

---

## ExamplePermission

Example handler with RBAC permission checking.

### `GET` `/api/v1/documents`

Get sensitive documents - requires additional permission

---

## Advertising

Handler for advertising platform API endpoints.

### `GET` `/api/v1/advertising/platforms` 🔒

List all supported advertising platforms and connection status

### `POST` `/api/v1/advertising/connect` 🔒

Connect an advertising platform with credentials

### `DELETE` `/api/v1/advertising/{platform}` 🔒

DELETE /api/v1/advertising/{platform}

### `GET` `/api/v1/advertising/campaigns` 🔒

Fetch campaigns from a specific platform

### `GET` `/api/v1/advertising/{platform}/campaigns` 🔒

Fetch campaigns from a specific platform

### `POST` `/api/v1/advertising/{platform}/campaigns` 🔒

Fetch campaigns from a specific platform

### `GET` `/api/v1/advertising/{platform}/campaigns/{campaign_id}` 🔒

GET /api/v1/advertising/{platform}/campaigns/{campaign_id}

### `PUT` `/api/v1/advertising/{platform}/campaigns/{campaign_id}` 🔒

PUT /api/v1/advertising/{platform}/campaigns/{campaign_id}

### `GET` `/api/v1/advertising/performance` 🔒

Run multi-agent analysis on advertising performance

### `GET` `/api/v1/advertising/{platform}/performance` 🔒

Run multi-agent analysis on advertising performance

### `POST` `/api/v1/advertising/analyze` 🔒

Run multi-agent analysis on advertising performance

### `GET` `/api/v1/advertising/budget-recommendations` 🔒

GET /api/v1/advertising/budget-recommendations

---

## AnalyticsPlatforms

Handler for analytics platform API endpoints.

### `GET` `/api/v1/analytics/platforms`

List all supported analytics platforms and connection status

### `GET` `/api/v1/analytics/connect`

Connect an analytics platform with credentials

### `GET` `/api/v1/analytics/{platform}`

GET /api/v1/analytics/{platform}

### `GET` `/api/v1/analytics/dashboards`

Fetch dashboards from a specific platform

### `GET` `/api/v1/analytics/{platform}/dashboards`

Fetch dashboards from a specific platform

### `GET` `/api/v1/analytics/{platform}/dashboards/{dashboard_id}`

GET /api/v1/analytics/{platform}/dashboards/{dashboard_id}

### `GET` `/api/v1/analytics/query`

Execute a query on a specific platform

### `GET` `/api/v1/analytics/reports`

List available pre-built reports

### `GET` `/api/v1/analytics/reports/generate`

Generate a custom analytics report

### `GET` `/api/v1/analytics/metrics`

Get a unified metrics overview across all platforms

### `GET` `/api/v1/analytics/realtime`

Get real-time metrics (primarily from GA4)

### `GET` `/api/v1/analytics/{platform}/events`

Get event data from a platform

### `GET` `/api/v1/analytics/{platform}/funnels`

Get funnel analysis from a platform

### `GET` `/api/v1/analytics/{platform}/retention`

Get retention analysis from a platform

---

## Audio

Audio and Podcast endpoint handlers.

### `GET` `/api/podcast/feed.xml`

iTunes-compatible RSS feed

### `GET` `/api/podcast/episodes`

JSON episode listing

---

## AuditSessions

Handler for audit session management endpoints.

### `GET` `/api/v1/audit/sessions` 🔒

List all audit sessions with optional filtering

### `POST` `/api/v1/audit/sessions` 🔒

List all audit sessions with optional filtering

### `GET` `/api/v1/audit/sessions/{session_id}` 🔒

GET /api/v1/audit/sessions/{session_id}

### `DELETE` `/api/v1/audit/sessions/{session_id}` 🔒

DELETE /api/v1/audit/sessions/{session_id}

### `POST` `/api/v1/audit/sessions/{session_id}/start` 🔒

Start an audit session

### `POST` `/api/v1/audit/sessions/{session_id}/pause` 🔒

Pause a running audit session

### `POST` `/api/v1/audit/sessions/{session_id}/resume` 🔒

Resume a paused audit session

### `POST` `/api/v1/audit/sessions/{session_id}/cancel` 🔒

Cancel an audit session using CancellationToken for cooperative abort

### `GET` `/api/v1/audit/sessions/{session_id}/findings` 🔒

Get findings for a session with optional filtering

### `GET` `/api/v1/audit/sessions/{session_id}/events` 🔒

Stream audit events via Server-Sent Events (SSE)

### `POST` `/api/v1/audit/sessions/{session_id}/intervene` 🔒

POST /api/v1/audit/sessions/{session_id}/intervene

### `GET` `/api/v1/audit/sessions/{session_id}/report` 🔒

Export audit report in various formats

---

## Broadcast

Broadcast generation handler.

### `POST` `/api/debates/{id}/broadcast` 🔒

Generate podcast audio from debate trace

### `GET` `/api/podcast/feed.xml`

Get RSS podcast feed

---

## Handler

Codebase Audit API Handler.

### `GET` `/api/v1/codebase/scan/{id}`

Get scan status/results

### `GET` `/api/v1/codebase/scans`

List past scans

### `GET` `/api/v1/codebase/findings`

Get aggregated findings

### `GET` `/api/v1/codebase/dashboard`

Get dashboard data

---

## Connectors

Handler for enterprise connector endpoints.

### `GET` `/api/v1/connectors`

List all configured connectors

### `GET` `/api/v1/connectors/{connector_id}`

GET /api/v1/connectors/{connector_id}

### `GET` `/api/v1/connectors/{connector_id}/sync`

Cancel a running sync operation

### `GET` `/api/v1/connectors/sync/{sync_id}/cancel`

Cancel a running sync operation

### `GET` `/api/v1/connectors/test`

Test a connector configuration without saving

### `GET` `/api/v1/connectors/sync-history`

GET /api/v1/connectors/sync-history

### `GET` `/api/v1/connectors/stats`

Get aggregate statistics for all connectors

### `GET` `/api/v1/connectors/health`

Get health scores for all connectors

### `GET` `/api/v1/connectors/types`

List all available connector types

---

## CRM

Handler for CRM platform API endpoints.

### `GET` `/api/v1/crm/platforms`

List all supported CRM platforms and connection status

### `POST` `/api/v1/crm/connect`

Connect a CRM platform with credentials

### `GET` `/api/v1/crm/status`

Get CRM handler status including circuit breaker state

### `DELETE` `/api/v1/crm/{platform}`

DELETE /api/v1/crm/{platform}

### `GET` `/api/v1/crm/contacts`

GET /api/v1/crm/contacts

### `GET` `/api/v1/crm/{platform}/contacts`

GET /api/v1/crm/{platform}/contacts

### `GET` `/api/v1/crm/{platform}/contacts/{contact_id}`

GET /api/v1/crm/{platform}/contacts/{contact_id}

### `GET` `/api/v1/crm/companies`

GET /api/v1/crm/companies

### `GET` `/api/v1/crm/{platform}/companies`

GET /api/v1/crm/{platform}/companies

### `GET` `/api/v1/crm/{platform}/companies/{company_id}`

GET /api/v1/crm/{platform}/companies/{company_id}

### `GET` `/api/v1/crm/deals`

GET /api/v1/crm/deals

### `GET` `/api/v1/crm/{platform}/deals`

GET /api/v1/crm/{platform}/deals

### `GET` `/api/v1/crm/{platform}/deals/{deal_id}`

GET /api/v1/crm/{platform}/deals/{deal_id}

### `GET` `/api/v1/crm/pipeline`

GET /api/v1/crm/pipeline

### `POST` `/api/v1/crm/sync-lead`

POST /api/v1/crm/sync-lead

### `POST` `/api/v1/crm/enrich`

POST /api/v1/crm/enrich

### `GET` `/api/v1/crm/search`

GET /api/v1/crm/search

---

## Cross Platform Analytics

Cross-Platform Analytics Dashboard Handler.

### `GET` `/api/v1/analytics/cross-platform/summary`

Unified dashboard summary

### `GET` `/api/v1/analytics/cross-platform/metrics`

Aggregated metrics

### `GET` `/api/v1/analytics/cross-platform/trends`

Cross-platform trends

### `GET` `/api/v1/analytics/cross-platform/comparison`

Platform comparison

### `GET` `/api/v1/analytics/cross-platform/correlation`

Metric correlation

### `GET` `/api/v1/analytics/cross-platform/anomalies`

Anomaly detection

### `GET` `/api/v1/analytics/cross-platform/alerts`

Active alerts

### `GET` `/api/v1/analytics/cross-platform/export`

Export data

### `GET` `/api/v1/analytics/cross-platform/demo`

Demo data

---

## Handler

DevOps Incident Management API Handler.

### `GET` `/api/v1/incidents`

List incidents

### `GET` `/api/v1/incidents/{id}` 🔒

Get incident details

### `GET` `/api/v1/oncall`

Get current on-call

### `GET` `/api/v1/services`

List services

### `GET` `/api/v1/services/{id}`

Get service details

### `GET` `/api/v1/devops/status`

Connection status

---

## Documents

Document management endpoint handlers.

### `GET` `/api/documents`

List all uploaded documents

### `GET` `/api/documents/formats`

Get supported file formats

### `POST` `/api/documents/upload` 🔒

Upload a document

---

## DocumentBatch

Handler for batch document upload and processing endpoints.

### `POST` `/api/v1/batch`

Generate unique batch ID

### `GET` `/api/v1/batch/queue/status`

Get status of a batch processing job

### `POST` `/api/v1/documents/batch`

Generate unique batch ID

### `GET` `/api/v1/documents/processing/stats`

Get batch processing statistics

### `GET` `/api/v1/knowledge/jobs`

List all knowledge processing jobs with optional filtering

---

## Ecommerce

Handler for e-commerce platform API endpoints with RBAC protection.

### `GET` `/api/v1/ecommerce/platforms`

List all supported e-commerce platforms and connection status

### `POST` `/api/v1/ecommerce/connect`

Connect an e-commerce platform with credentials

### `DELETE` `/api/v1/ecommerce/{platform}`

DELETE /api/v1/ecommerce/{platform}

### `GET` `/api/v1/ecommerce/orders`

Fetch orders from a specific platform

### `GET` `/api/v1/ecommerce/{platform}/orders`

Fetch orders from a specific platform

### `GET` `/api/v1/ecommerce/{platform}/orders/{order_id}`

GET /api/v1/ecommerce/{platform}/orders/{order_id}

### `GET` `/api/v1/ecommerce/products`

Fetch products from a specific platform

### `GET` `/api/v1/ecommerce/{platform}/products`

Fetch products from a specific platform

### `GET` `/api/v1/ecommerce/{platform}/products/{product_id}`

GET /api/v1/ecommerce/{platform}/products/{product_id}

### `GET` `/api/v1/ecommerce/inventory`

Get inventory levels across platforms

### `POST` `/api/v1/ecommerce/sync-inventory`

POST /api/v1/ecommerce/sync-inventory

### `GET` `/api/v1/ecommerce/fulfillment`

Get fulfillment status for orders

### `POST` `/api/v1/ecommerce/ship`

Create a shipment for an order

### `GET` `/api/v1/ecommerce/metrics`

Fetch metrics from a specific platform

### `GET` `/api/v1/ecommerce/circuit-breaker`

GET /api/v1/ecommerce/circuit-breaker

---

## Email Webhooks

Email Webhook Handlers.

### `GET` `/api/v1/webhooks/status`

Get webhook subscription status

---

## Features

Handler for feature availability endpoints.

### `GET` `/api/v1/features`

Get full feature matrix

### `GET` `/api/v1/features/all`

Get flat list of all API endpoints

### `GET` `/api/v1/features/available`

Get list of available features

### `GET` `/api/v1/features/config`

Get user's feature configuration

### `GET` `/api/v1/features/discover`

Get comprehensive API discovery catalog

### `GET` `/api/v1/features/endpoints`

Get flat list of all API endpoints

### `GET` `/api/v1/features/handlers`

GET /api/v1/features/handlers

### `GET` `/api/features`

Get flat list of all API endpoints

### `GET` `/api/features/all`

Get flat list of all API endpoints

### `GET` `/api/features/available`

Get list of available features

### `GET` `/api/features/config`

Get user's feature configuration

### `GET` `/api/features/discover`

Get flat list of all API endpoints

### `GET` `/api/features/endpoints`

Get flat list of all API endpoints

### `GET` `/api/features/handlers`

GET /api/features/handlers

---

## GmailLabels

Handler for Gmail labels and message modification endpoints.

### `GET` `/api/v1/gmail/labels` 🔒

Modify message labels via Gmail API

### `POST` `/api/v1/gmail/labels` 🔒

Modify message labels via Gmail API

### `GET` `/api/v1/gmail/filters` 🔒

List filters via Gmail API

### `POST` `/api/v1/gmail/filters` 🔒

List filters via Gmail API

---

## GmailThreads

Handler for Gmail threads and drafts endpoints.

### `GET` `/api/v1/gmail/threads` 🔒

List threads via Gmail API

### `GET` `/api/v1/gmail/drafts` 🔒

List drafts via Gmail API

### `POST` `/api/v1/gmail/drafts` 🔒

List drafts via Gmail API

---

## Integrations

Handler for integration management endpoints.

### `GET` `/api/v1/integrations`

GET /api/v1/integrations

### `POST` `/api/v1/integrations`

POST /api/v1/integrations

### `GET` `/api/v1/integrations/status`

GET /api/v1/integrations/status

### `GET` `/api/v1/integrations/available`

GET /api/v1/integrations/available

### `POST` `/api/v1/integrations/config`

POST /api/v1/integrations/config

---

## Legal

Legal E-Signature API Handler.

### `GET` `/api/v1/legal/envelopes`

List envelopes

### `GET` `/api/v1/legal/envelopes/{id}`

Get envelope details

### `GET` `/api/v1/legal/envelopes/{id}/documents/{doc_id}`

Download document

### `GET` `/api/v1/legal/envelopes/{id}/certificate`

Download certificate

### `GET` `/api/v1/legal/status`

Connection status

---

## Handler

Marketplace Handler - Template discovery and deployment.

### `GET` `/api/v1/marketplace/templates`

List all available templates

### `GET` `/api/v1/marketplace/templates/{id}`

Get template details

### `GET` `/api/v1/marketplace/categories`

List template categories

### `GET` `/api/v1/marketplace/search`

Search templates

### `GET` `/api/v1/marketplace/deployments`

List deployed templates

### `GET` `/api/v1/marketplace/popular`

Get popular templates

### `GET` `/api/v1/marketplace/demo`

Get demo marketplace data

### `GET` `/api/v1/marketplace/status`

Circuit breaker and health status

---

## Outlook

Outlook/Microsoft 365 Email Handler.

### `GET` `/api/v1/outlook/oauth/url` 🔒

Get OAuth authorization URL

### `POST` `/api/v1/outlook/oauth/callback` 🔒

Handle OAuth callback

### `GET` `/api/v1/outlook/folders` 🔒

List mail folders

### `GET` `/api/v1/outlook/messages` 🔒

List messages

### `GET` `/api/v1/outlook/messages/{id}` 🔒

Get message details

### `GET` `/api/v1/outlook/conversations/{id}` 🔒

Get conversation thread

### `POST` `/api/v1/outlook/send` 🔒

Send new message

### `POST` `/api/v1/outlook/reply` 🔒

Reply to message

### `GET` `/api/v1/outlook/search` 🔒

Search messages

### `POST` `/api/v1/outlook/messages/{id}/read` 🔒

Mark as read/unread

### `POST` `/api/v1/outlook/messages/{id}/move` 🔒

Move message

### `DELETE` `/api/v1/outlook/messages/{id}` 🔒

Delete message

---

## Plugins

Plugins endpoint handlers.

### `GET` `/api/plugins` 🔒

List all available plugins

### `GET` `/api/plugins/{name}`

Get details for a specific plugin

### `POST` `/api/plugins/{name}/run` 🔒

Run a plugin with provided input

### `GET` `/api/plugins/installed` 🔒

List installed plugins for user/org

### `POST` `/api/plugins/{name}/install` 🔒

Install a plugin

### `DELETE` `/api/plugins/{name}/install` 🔒

Uninstall a plugin

### `POST` `/api/plugins/submit` 🔒

Submit a new plugin for review

### `GET` `/api/plugins/submissions` 🔒

List user's plugin submissions

---

## Pulse

Pulse and trending topics endpoint handlers.

### `GET` `/api/pulse/trending`

Get trending topics from multiple sources

### `GET` `/api/pulse/suggest`

Suggest a trending topic for debate

---

## Reconciliation

Bank Reconciliation API Handler.

### `POST` `/api/v1/reconciliation/run` 🔒

Run new reconciliation

### `GET` `/api/v1/reconciliation/list`

List past reconciliations

### `GET` `/api/v1/reconciliation/{id}`

Get reconciliation details

### `GET` `/api/v1/reconciliation/{id}/report`

Generate PDF report

### `POST` `/api/v1/reconciliation/{id}/resolve` 🔒

Resolve a discrepancy

### `POST` `/api/v1/reconciliation/{id}/approve` 🔒

Approve reconciliation

### `GET` `/api/v1/reconciliation/discrepancies`

Get all pending discrepancies

### `POST` `/api/v1/reconciliation/discrepancies/bulk-resolve` 🔒

Bulk resolve

---

## RoutingRules

Handler for routing rules CRUD and evaluation endpoints.

### `GET` `/api/v1/routing-rules`

GET /api/v1/routing-rules

### `GET` `/api/v1/routing-rules/{rule_id}`

GET /api/v1/routing-rules/{rule_id}

### `GET` `/api/v1/routing-rules/{rule_id}/toggle`

Toggle a rule's enabled state

### `GET` `/api/v1/routing-rules/evaluate`

Evaluate rules against a context for testing

### `GET` `/api/v1/routing-rules/templates`

Get predefined rule templates

---

## Support

Handler for support platform API endpoints.

### `GET` `/api/v1/support/platforms`

List all supported support platforms and connection status

### `POST` `/api/v1/support/connect`

Connect a support platform with credentials

### `DELETE` `/api/v1/support/{platform}`

DELETE /api/v1/support/{platform}

### `GET` `/api/v1/support/tickets`

Fetch tickets from a specific platform

### `POST` `/api/v1/support/{platform}/tickets`

Fetch tickets from a specific platform

### `PUT` `/api/v1/support/{platform}/tickets/{ticket_id}`

PUT /api/v1/support/{platform}/tickets/{ticket_id}

### `POST` `/api/v1/support/{platform}/tickets/{ticket_id}/reply`

Reply to a ticket

### `GET` `/api/v1/support/metrics`

Fetch metrics from a specific platform

### `POST` `/api/v1/support/triage`

AI-powered ticket triage using multi-agent analysis

### `POST` `/api/v1/support/auto-respond`

POST /api/v1/support/auto-respond

### `GET` `/api/v1/support/search`

Coerce search platform inputs to a normalized list of platform ids

---

## Handler

Unified Inbox API Handler.

### `GET` `/api/v1/inbox/oauth/gmail` 🔒

Get Gmail OAuth URL (redirect_uri required)

### `GET` `/api/v1/inbox/oauth/outlook` 🔒

Get Outlook OAuth URL (redirect_uri required)

### `POST` `/api/v1/inbox/connect` 🔒

Connect Gmail or Outlook account

### `GET` `/api/v1/inbox/accounts` 🔒

List connected accounts

### `DELETE` `/api/v1/inbox/accounts/{id}` 🔒

Disconnect an account

### `GET` `/api/v1/inbox/messages` 🔒

Get prioritized messages across accounts

### `GET` `/api/v1/inbox/messages/{id}` 🔒

Get single message details

### `POST` `/api/v1/inbox/messages/{id}/debate` 🔒

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

## Status

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

## Accounting

Accounting handlers for QuickBooks Online and Gusto payroll integration.

### `GET` `/api/accounting/status` 🔒

QuickBooks status + dashboard data

### `GET` `/api/accounting/connect` 🔒

Start QuickBooks OAuth

### `GET` `/api/accounting/callback` 🔒

QuickBooks OAuth callback

### `POST` `/api/accounting/disconnect` 🔒

Disconnect QuickBooks

### `GET` `/api/accounting/customers` 🔒

List QuickBooks customers

### `GET` `/api/accounting/transactions` 🔒

List QuickBooks transactions

### `POST` `/api/accounting/report` 🔒

Generate accounting report

### `GET` `/api/accounting/gusto/status` 🔒

Gusto connection status

### `GET` `/api/accounting/gusto/connect` 🔒

Start Gusto OAuth

### `GET` `/api/accounting/gusto/callback` 🔒

Gusto OAuth callback

### `POST` `/api/accounting/gusto/disconnect` 🔒

Disconnect Gusto

### `GET` `/api/accounting/gusto/employees` 🔒

List employees

### `GET` `/api/accounting/gusto/payrolls` 🔒

List payroll runs

### `GET` `/api/accounting/gusto/payrolls/{payroll_id}` 🔒

Payroll run details

### `POST` `/api/accounting/gusto/payrolls/{payroll_id}/journal-entry` 🔒

Generate journal entry

---

## Ap Automation

HTTP API Handlers for Accounts Payable Automation.

### `POST` `/api/v1/accounting/ap/invoices`

Add payable invoice

### `GET` `/api/v1/accounting/ap/invoices`

List payable invoices

### `GET` `/api/v1/accounting/ap/invoices/{id}`

Get invoice by ID

### `POST` `/api/v1/accounting/ap/invoices/{id}/payment`

Record payment

### `POST` `/api/v1/accounting/ap/optimize`

Optimize payment timing

### `POST` `/api/v1/accounting/ap/batch`

Create batch payment

### `GET` `/api/v1/accounting/ap/forecast`

Get cash flow forecast

### `GET` `/api/v1/accounting/ap/discounts`

Get discount opportunities

---

## Ar Automation

HTTP API Handlers for Accounts Receivable Automation.

### `POST` `/api/v1/accounting/ar/invoices`

Create invoice

### `GET` `/api/v1/accounting/ar/invoices`

List invoices

### `GET` `/api/v1/accounting/ar/invoices/{id}`

Get invoice by ID

### `POST` `/api/v1/accounting/ar/invoices/{id}/send`

Send invoice to customer

### `POST` `/api/v1/accounting/ar/invoices/{id}/reminder`

Send payment reminder

### `POST` `/api/v1/accounting/ar/invoices/{id}/payment`

Record payment

### `GET` `/api/v1/accounting/ar/aging`

Get AR aging report

### `GET` `/api/v1/accounting/ar/collections`

Get collection suggestions

### `POST` `/api/v1/accounting/ar/customers`

Add customer

### `GET` `/api/v1/accounting/ar/customers/{id}/balance`

Get customer balance

---

## Expenses

HTTP API Handlers for Expense Tracking.

### `POST` `/api/v1/accounting/expenses/upload`

Upload and process receipt

### `POST` `/api/v1/accounting/expenses`

Create expense manually

### `GET` `/api/v1/accounting/expenses`

List expenses with filters

### `GET` `/api/v1/accounting/expenses/{id}`

Get expense by ID

### `PUT` `/api/v1/accounting/expenses/{id}`

Update expense

### `DELETE` `/api/v1/accounting/expenses/{id}`

Delete expense

### `POST` `/api/v1/accounting/expenses/{id}/approve`

Approve expense

### `POST` `/api/v1/accounting/expenses/{id}/reject`

Reject expense

### `POST` `/api/v1/accounting/expenses/categorize`

Auto-categorize expenses

### `POST` `/api/v1/accounting/expenses/sync`

Sync expenses to QBO

### `GET` `/api/v1/accounting/expenses/stats`

Get expense statistics

### `GET` `/api/v1/accounting/expenses/pending`

Get pending approvals

### `GET` `/api/v1/accounting/expenses/export`

Export expenses

---

## Invoices

HTTP API Handlers for Invoice Processing.

### `POST` `/api/v1/accounting/invoices/upload`

Upload and extract invoice

### `POST` `/api/v1/accounting/invoices`

Create invoice manually

### `GET` `/api/v1/accounting/invoices`

List invoices with filters

### `GET` `/api/v1/accounting/invoices/{id}`

Get invoice by ID

### `POST` `/api/v1/accounting/invoices/{id}/approve`

Approve invoice

### `POST` `/api/v1/accounting/invoices/{id}/reject`

Reject invoice

### `POST` `/api/v1/accounting/invoices/{id}/match`

Match to PO

### `POST` `/api/v1/accounting/invoices/{id}/schedule`

Schedule payment

### `GET` `/api/v1/accounting/invoices/{id}/anomalies`

Get anomalies

### `GET` `/api/v1/accounting/invoices/pending`

Get pending approvals

### `GET` `/api/v1/accounting/invoices/overdue`

Get overdue invoices

### `GET` `/api/v1/accounting/invoices/stats`

Get statistics

### `POST` `/api/v1/accounting/purchase-orders`

Add purchase order

### `GET` `/api/v1/accounting/payments/scheduled`

Get scheduled payments

---

## GatewayAgents

HTTP request handler for external agent registration endpoints.

### `POST` `/api/v1/gateway/agents`

Extract agent name from path like /api/v1/gateway/agents/{name}

### `DELETE` `/api/v1/gateway/agents`

Extract agent name from path like /api/v1/gateway/agents/{name}

---

## GatewayConfig

HTTP handler for gateway configuration endpoints.

### `POST` `/api/v1/gateway/config`

Handle GET /api/v1/gateway/config

### `POST` `/api/v1/gateway/config/defaults`

Handle GET /api/v1/gateway/config/defaults

---

## GatewayCredentials

HTTP request handler for gateway credential management endpoints.

### `POST` `/api/v1/gateway/credentials`

Extract credential ID from path like /api/v1/gateway/credentials/{id}

### `DELETE` `/api/v1/gateway/credentials`

Extract credential ID from path like /api/v1/gateway/credentials/{id}

---

## Gateway

HTTP request handler for gateway API endpoints.

### `GET` `/api/v1/gateway/devices`

Handle GET /api/v1/gateway/devices/{id}

### `POST` `/api/v1/gateway/devices`

Handle GET /api/v1/gateway/devices/{id}

### `GET` `/api/v1/gateway/channels`

Handle GET /api/v1/gateway/channels

### `POST` `/api/v1/gateway/channels`

Handle GET /api/v1/gateway/channels

### `GET` `/api/v1/gateway/routing`

Handle GET /api/v1/gateway/routing/rules

### `POST` `/api/v1/gateway/routing`

Handle GET /api/v1/gateway/routing/rules

### `GET` `/api/v1/gateway/routing/rules`

Handle GET /api/v1/gateway/routing/rules

### `GET` `/api/v1/gateway/routing/stats`

Handle GET /api/v1/gateway/routing/stats

### `GET` `/api/v1/gateway/messages`

Handle POST /api/v1/gateway/messages/route

### `POST` `/api/v1/gateway/messages`

Handle POST /api/v1/gateway/messages/route

### `POST` `/api/v1/gateway/messages/route`

Get or create agent router

---

## GatewayHealth

HTTP handler for gateway health endpoints.

### `GET` `/api/v1/gateway/health`

Handle GET /api/v1/gateway/agents/{name}/health

---

## Gauntlet

Handler for gauntlet stress-testing endpoints.

### `GET` `/api/gauntlet/run`

GET /api/gauntlet/run

### `GET` `/api/gauntlet/personas`

GET /api/gauntlet/personas

### `GET` `/api/gauntlet/results`

GET /api/gauntlet/results

### `GET` `/api/gauntlet/receipts`

GET /api/gauntlet/receipts

### `GET` `/api/v1/gauntlet/run`

GET /api/v1/gauntlet/run

### `POST` `/api/v1/gauntlet/run` 🔒

POST /api/v1/gauntlet/run

### `GET` `/api/v1/gauntlet/personas`

GET /api/v1/gauntlet/personas

### `GET` `/api/v1/gauntlet/results`

GET /api/v1/gauntlet/results

### `GET` `/api/v1/gauntlet`

Normalize path by removing version prefix for routing logic

### `GET` `/api/v1/gauntlet/heatmaps`

GET /api/v1/gauntlet/heatmaps

### `GET` `/api/v1/gauntlet/receipts`

GET /api/v1/gauntlet/receipts

### `POST` `/api/v1/gauntlet/receipts/export/bundle`

POST /api/v1/gauntlet/receipts/export/bundle

### `GET` `/api/v1/receipts/recent-anchors` 🔒

GET /api/v1/receipts/recent-anchors

---

## Audit Bridge

Audit-to-GitHub Bridge Handler.

### `POST` `/api/v1/github/audit/issues` 🔒

Create issues from findings

### `POST` `/api/v1/github/audit/issues/bulk` 🔒

Bulk create issues

### `POST` `/api/v1/github/audit/pr` 🔒

Create PR with fixes

### `GET` `/api/v1/github/audit/sync/{session_id}` 🔒

Get sync status

### `POST` `/api/v1/github/audit/sync/{session_id}` 🔒

Sync session to GitHub

---

## Pr Review

HTTP API Handlers for GitHub Pull Request Review.

### `POST` `/api/v1/github/pr/review` 🔒

Trigger PR review

### `GET` `/api/v1/github/pr/{pr_number}` 🔒

Get PR details

### `POST` `/api/v1/github/pr/{pr_number}/review` 🔒

Submit review

### `GET` `/api/v1/github/pr/{pr_number}/reviews` 🔒

List reviews

---

## UnifiedApprovals

Aggregate approval requests across subsystems.

### `GET` `/api/v1/approvals`

GET /api/v1/approvals

### `GET` `/api/v1/approvals/pending`

GET /api/v1/approvals/pending

---

## Moderation

Handler for moderation configuration and review queue.

### `GET` `/api/moderation/config`

GET /api/moderation/config

### `PUT` `/api/moderation/config`

PUT /api/moderation/config

### `GET` `/api/moderation/stats`

GET /api/moderation/stats

### `GET` `/api/moderation/queue`

GET /api/moderation/queue

---

## Outcome

Handler for decision outcome tracking API endpoints.

### `POST` `/api/outcomes/search`

GET /api/v1/outcomes/search?q=

### `POST` `/api/outcomes/impact`

GET /api/v1/outcomes/impact  Impact analytics across all outcomes

---

## ReviewQueue

HTTP handler for PDB UI v0 review-queue endpoints.

### `GET` `/api/review-queue/triage-metrics` 🔒

GET /api/review-queue/triage-metrics

### `GET` `/api/v1/review-queue/triage-metrics` 🔒

GET /api/v1/review-queue/triage-metrics

---

## Settlement

Handler for settlement API endpoints.

### `GET` `/api/settlements` 🔒

GET /api/settlements

### `GET` `/api/settlements/history` 🔒

Get settled (resolved) settlements

### `GET` `/api/settlements/summary` 🔒

Get overall settlement summary statistics

### `GET` `/api/settlements/{id}` 🔒

GET /api/settlements/{id}

### `POST` `/api/settlements/{id}/settle` 🔒

Get a specific settlement by ID

### `POST` `/api/settlements/batch` 🔒

Settle multiple claims at once

### `GET` `/api/settlements/agent/{agent}/accuracy` 🔒

Get accuracy statistics for a specific agent

### `GET` `/api/v1/settlements` 🔒

GET /api/v1/settlements

### `GET` `/api/v1/settlements/history` 🔒

Get settled (resolved) settlements

### `GET` `/api/v1/settlements/summary` 🔒

Get overall settlement summary statistics

### `GET` `/api/v1/settlements/{id}` 🔒

GET /api/v1/settlements/{id}

### `POST` `/api/v1/settlements/{id}/settle` 🔒

Get a specific settlement by ID

### `POST` `/api/v1/settlements/batch` 🔒

Settle multiple claims at once

### `GET` `/api/v1/settlements/agent/{agent}/accuracy` 🔒

Get accuracy statistics for a specific agent

---

## Inbox Command

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

---

## Team Inbox

HTTP API Handlers for Team Inbox Collaboration.

### `GET` `/api/v1/inbox/shared/{id}/team` 🔒

Get team members

### `POST` `/api/v1/inbox/shared/{id}/team` 🔒

Add team member

### `GET` `/api/v1/inbox/mentions` 🔒

Get mentions for current user

### `POST` `/api/v1/inbox/mentions/{id}/acknowledge` 🔒

Acknowledge mention

### `GET` `/api/v1/inbox/shared/{id}/activity` 🔒

Get activity feed

---

## InboxTrustWedge

Expose receipt-gated inbox wedge actions over HTTP.

### `GET` `/api/v1/inbox/wedge/receipts` 🔒

GET /api/v1/inbox/wedge/receipts

### `POST` `/api/v1/inbox/wedge/receipts` 🔒

POST /api/v1/inbox/wedge/receipts

---

## Automation

HTTP Handler for Automation Platform Webhooks.

### `DELETE` `/api/v1/webhooks/{id}` 🔒

Remove subscription

### `GET` `/api/v1/webhooks` 🔒

List subscriptions

### `GET` `/api/v1/webhooks/{id}` 🔒

Get subscription details

### `POST` `/api/v1/webhooks/{id}/test` 🔒

Test subscription

### `GET` `/api/v1/webhooks/events`

List available event types

### `POST` `/api/v1/webhooks/dispatch`

Dispatch event (internal)

---

## Bindings

Bindings endpoint handlers.

### `GET` `/api/bindings`

List all message bindings

### `POST` `/api/bindings`

Create a new binding

### `POST` `/api/bindings/resolve`

Resolve binding for a message

### `GET` `/api/bindings/stats`

Get router statistics

---

## ComputerUse

HTTP request handler for computer use API endpoints.

### `GET` `/api/v1/computer-use/tasks` 🔒

Handle POST /api/v1/computer-use/tasks/{id}/cancel

### `POST` `/api/v1/computer-use/tasks` 🔒

Handle POST /api/v1/computer-use/tasks/{id}/cancel

### `GET` `/api/v1/computer-use/actions` 🔒

Handle GET /api/v1/computer-use/actions/stats

### `POST` `/api/v1/computer-use/actions` 🔒

Handle GET /api/v1/computer-use/actions/stats

### `GET` `/api/v1/computer-use/actions/stats` 🔒

Handle GET /api/v1/computer-use/actions/stats

### `GET` `/api/v1/computer-use/policies` 🔒

Handle POST /api/v1/computer-use/policies

### `POST` `/api/v1/computer-use/policies` 🔒

Handle POST /api/v1/computer-use/policies

### `GET` `/api/v1/computer-use/approvals` 🔒

Handle POST /api/v1/computer-use/approvals/{id}/approve

---

## ERC8004

Handler for ERC-8004 blockchain API endpoints.

### `GET` `/api/v1/blockchain/config`

GET /api/v1/blockchain/config

### `GET` `/api/v1/blockchain/health`

GET /api/v1/blockchain/health

### `GET` `/api/v1/blockchain/sync`

GET /api/v1/blockchain/sync

### `POST` `/api/v1/blockchain/sync` 🔒

POST /api/v1/blockchain/sync

### `GET` `/api/v1/blockchain/agents`

GET /api/v1/blockchain/agents

### `POST` `/api/v1/blockchain/agents` 🔒

POST /api/v1/blockchain/agents

---

## Health

Integration health check endpoint handler.

### `GET` `/api/v1/integrations/health`

Returns health status for each configured

---

## Integration Management

Integration Management HTTP Handlers for Aragora.

### `GET` `/api/v2/integrations`

List all integrations

### `GET` `/api/v2/integrations/:type`

Get specific integration status

### `DELETE` `/api/v2/integrations/:type`

Disconnect integration

### `POST` `/api/v2/integrations/:type/test`

Test integration connectivity

### `GET` `/api/v2/integrations/stats`

Integration statistics

---

## Adapters

Knowledge Mound adapter status endpoint handler.

### `GET` `/api/v1/knowledge/adapters`

List all KM adapters with status, priority,

---

## KMCheckpoint

Handler for Knowledge Mound checkpoint management endpoints.

### `POST` `/api/v1/km/checkpoints/compare` 🔒

Compare checkpoint with current KM state

---

## KnowledgeChat

HTTP handler for Knowledge + Chat bridge endpoints.

### `POST` `/api/v1/chat/knowledge/search` 🔒

POST /api/v1/chat/knowledge/search

### `POST` `/api/v1/chat/knowledge/inject` 🔒

POST /api/v1/chat/knowledge/inject

### `POST` `/api/v1/chat/knowledge/store` 🔒

POST /api/v1/chat/knowledge/store

---

## RLMContext

Handler for RLM context compression and query endpoints.

### `GET` `/api/v1/rlm/stats`

GET /api/v1/rlm/stats

### `GET` `/api/v1/rlm/strategies`

GET /api/v1/rlm/strategies

### `POST` `/api/v1/rlm/compress`

Get or create the hierarchical compressor using factory

### `POST` `/api/v1/rlm/query`

Simple fallback query when full RLM is not available

### `GET` `/api/v1/rlm/contexts`

GET /api/v1/rlm/contexts

### `POST` `/api/v1/rlm/stream`

POST /api/v1/rlm/stream

### `GET` `/api/v1/rlm/stream/modes`

GET /api/v1/rlm/stream/modes

### `GET` `/api/v1/rlm/codebase/health`

GET /api/v1/rlm/codebase/health

---

## Knowledge

Handler for knowledge base API endpoints.

### `POST` `/api/v1/knowledge/query` 🔒

Get or create query engine

### `GET` `/api/v1/knowledge/facts` 🔒

Handle /api/v1/knowledge/facts/:id/* routes

### `POST` `/api/v1/knowledge/facts` 🔒

Handle /api/v1/knowledge/facts/:id/* routes

### `POST` `/api/v1/knowledge/facts/relations` 🔒

POST /api/v1/knowledge/facts/relations

### `GET` `/api/v1/knowledge/search` 🔒

GET /api/v1/knowledge/search

### `GET` `/api/v1/knowledge/stats` 🔒

GET /api/v1/knowledge/stats

### `GET` `/api/v1/knowledge/embeddings`

GET /api/v1/knowledge/embeddings

### `GET` `/api/v1/knowledge/export`

GET /api/v1/knowledge/export

### `GET` `/api/v1/knowledge/refresh`

GET /api/v1/knowledge/refresh

### `GET` `/api/v1/knowledge/validate`

GET /api/v1/knowledge/validate

### `GET` `/api/v1/facts`

Normalize /api/v1/facts/* to /api/v1/knowledge/facts/* for routing

### `GET` `/api/v1/facts/batch`

Handle POST /api/v1/index/embed-batch with the local model /api/v1/ml/embed uses

### `GET` `/api/v1/facts/batch/delete`

GET /api/v1/facts/batch/delete

### `GET` `/api/v1/facts/merge`

GET /api/v1/facts/merge

### `GET` `/api/v1/facts/relationships`

GET /api/v1/facts/relationships

### `GET` `/api/v1/facts/stats`

GET /api/v1/facts/stats

### `GET` `/api/v1/facts/validate`

GET /api/v1/facts/validate

### `GET` `/api/v1/index`

Handle POST /api/v1/index/embed-batch with the local model /api/v1/ml/embed uses

### `GET` `/api/v1/index/embed-batch`

Handle POST /api/v1/index/embed-batch with the local model /api/v1/ml/embed uses

### `GET` `/api/v1/index/search`

GET /api/v1/index/search

---

## KnowledgeMound

Handler for Knowledge Mound API endpoints (unified knowledge storage).

### `GET` `/api/v1/knowledge/mound/query`

GET /api/v1/knowledge/mound/query

### `POST` `/api/v1/knowledge/mound/query` 🔒

POST /api/v1/knowledge/mound/query

### `GET` `/api/v1/knowledge/mound/nodes`

GET /api/v1/knowledge/mound/nodes

### `POST` `/api/v1/knowledge/mound/nodes` 🔒

POST /api/v1/knowledge/mound/nodes

### `GET` `/api/v1/knowledge/mound/relationships`

GET /api/v1/knowledge/mound/relationships

### `POST` `/api/v1/knowledge/mound/relationships` 🔒

POST /api/v1/knowledge/mound/relationships

### `GET` `/api/v1/knowledge/mound/stats`

GET /api/v1/knowledge/mound/stats

### `GET` `/api/v1/knowledge/mound/culture`

GET /api/v1/knowledge/mound/culture

### `GET` `/api/v1/knowledge/mound/stale`

GET /api/v1/knowledge/mound/stale

### `GET` `/api/v1/knowledge/mound/revalidate`

GET /api/v1/knowledge/mound/revalidate

### `GET` `/api/v1/knowledge/mound/schedule-revalidation`

GET /api/v1/knowledge/mound/schedule-revalidation

### `POST` `/api/v1/knowledge/mound/schedule-revalidation` 🔒

POST /api/v1/knowledge/mound/schedule-revalidation

### `GET` `/api/v1/knowledge/mound/sync`

GET /api/v1/knowledge/mound/sync

### `GET` `/api/v1/knowledge/mound/export/d3`

GET /api/v1/knowledge/mound/export/d3

### `GET` `/api/v1/knowledge/mound/export/graphml`

GET /api/v1/knowledge/mound/export/graphml

### `GET` `/api/v1/knowledge/mound/share`

GET /api/v1/knowledge/mound/share

### `POST` `/api/v1/knowledge/mound/share` 🔒

POST /api/v1/knowledge/mound/share

### `PATCH` `/api/v1/knowledge/mound/share` 🔒

PATCH /api/v1/knowledge/mound/share

### `DELETE` `/api/v1/knowledge/mound/share` 🔒

DELETE /api/v1/knowledge/mound/share

### `GET` `/api/v1/knowledge/mound/shared-with-me`

GET /api/v1/knowledge/mound/shared-with-me

### `GET` `/api/v1/knowledge/mound/my-shares`

GET /api/v1/knowledge/mound/my-shares

### `GET` `/api/v1/knowledge/mound/global`

GET /api/v1/knowledge/mound/global

### `POST` `/api/v1/knowledge/mound/global` 🔒

POST /api/v1/knowledge/mound/global

### `GET` `/api/v1/knowledge/mound/global/facts`

GET /api/v1/knowledge/mound/global/facts

### `GET` `/api/v1/knowledge/mound/global/promote`

GET /api/v1/knowledge/mound/global/promote

### `POST` `/api/v1/knowledge/mound/global/promote` 🔒

POST /api/v1/knowledge/mound/global/promote

### `GET` `/api/v1/knowledge/mound/federation/regions`

GET /api/v1/knowledge/mound/federation/regions

### `POST` `/api/v1/knowledge/mound/federation/regions` 🔒

POST /api/v1/knowledge/mound/federation/regions

### `GET` `/api/v1/knowledge/mound/federation/status`

GET /api/v1/knowledge/mound/federation/status

### `GET` `/api/v1/knowledge/mound/federation/sync/push`

GET /api/v1/knowledge/mound/federation/sync/push

### `POST` `/api/v1/knowledge/mound/federation/sync/push` 🔒

POST /api/v1/knowledge/mound/federation/sync/push

### `GET` `/api/v1/knowledge/mound/federation/sync/pull`

GET /api/v1/knowledge/mound/federation/sync/pull

### `POST` `/api/v1/knowledge/mound/federation/sync/pull` 🔒

POST /api/v1/knowledge/mound/federation/sync/pull

### `GET` `/api/v1/knowledge/mound/federation/sync/all`

GET /api/v1/knowledge/mound/federation/sync/all

### `POST` `/api/v1/knowledge/mound/federation/sync/all` 🔒

POST /api/v1/knowledge/mound/federation/sync/all

### `GET` `/api/v1/knowledge/mound/index/repository`

GET /api/v1/knowledge/mound/index/repository

### `POST` `/api/v1/knowledge/mound/index/repository` 🔒

POST /api/v1/knowledge/mound/index/repository

### `GET` `/api/v1/knowledge/mound/dedup/clusters`

GET /api/v1/knowledge/mound/dedup/clusters

### `GET` `/api/v1/knowledge/mound/dedup/report`

GET /api/v1/knowledge/mound/dedup/report

### `GET` `/api/v1/knowledge/mound/dedup/merge`

GET /api/v1/knowledge/mound/dedup/merge

### `POST` `/api/v1/knowledge/mound/dedup/merge` 🔒

POST /api/v1/knowledge/mound/dedup/merge

### `GET` `/api/v1/knowledge/mound/dedup/auto-merge`

GET /api/v1/knowledge/mound/dedup/auto-merge

### `POST` `/api/v1/knowledge/mound/dedup/auto-merge` 🔒

POST /api/v1/knowledge/mound/dedup/auto-merge

### `GET` `/api/v1/knowledge/mound/pruning/items`

GET /api/v1/knowledge/mound/pruning/items

### `GET` `/api/v1/knowledge/mound/pruning/execute`

GET /api/v1/knowledge/mound/pruning/execute

### `POST` `/api/v1/knowledge/mound/pruning/execute` 🔒

POST /api/v1/knowledge/mound/pruning/execute

### `GET` `/api/v1/knowledge/mound/pruning/auto`

GET /api/v1/knowledge/mound/pruning/auto

### `POST` `/api/v1/knowledge/mound/pruning/auto` 🔒

POST /api/v1/knowledge/mound/pruning/auto

### `GET` `/api/v1/knowledge/mound/pruning/history`

GET /api/v1/knowledge/mound/pruning/history

### `GET` `/api/v1/knowledge/mound/pruning/restore`

GET /api/v1/knowledge/mound/pruning/restore

### `POST` `/api/v1/knowledge/mound/pruning/restore` 🔒

POST /api/v1/knowledge/mound/pruning/restore

### `GET` `/api/v1/knowledge/mound/pruning/decay`

GET /api/v1/knowledge/mound/pruning/decay

### `POST` `/api/v1/knowledge/mound/pruning/decay` 🔒

POST /api/v1/knowledge/mound/pruning/decay

### `GET` `/api/v1/knowledge/mound/dashboard/health`

GET /api/v1/knowledge/mound/dashboard/health

### `GET` `/api/v1/knowledge/mound/dashboard/metrics`

GET /api/v1/knowledge/mound/dashboard/metrics

### `GET` `/api/v1/knowledge/mound/dashboard/metrics/reset`

GET /api/v1/knowledge/mound/dashboard/metrics/reset

### `POST` `/api/v1/knowledge/mound/dashboard/metrics/reset` 🔒

POST /api/v1/knowledge/mound/dashboard/metrics/reset

### `GET` `/api/v1/knowledge/mound/dashboard/adapters`

GET /api/v1/knowledge/mound/dashboard/adapters

### `GET` `/api/v1/knowledge/mound/dashboard/queries`

GET /api/v1/knowledge/mound/dashboard/queries

### `GET` `/api/v1/knowledge/mound/dashboard/batcher`

GET /api/v1/knowledge/mound/dashboard/batcher

### `GET` `/api/v1/knowledge/mound/curation/policy`

GET /api/v1/knowledge/mound/curation/policy

### `POST` `/api/v1/knowledge/mound/curation/policy` 🔒

POST /api/v1/knowledge/mound/curation/policy

### `PUT` `/api/v1/knowledge/mound/curation/policy` 🔒

PUT /api/v1/knowledge/mound/curation/policy

### `GET` `/api/v1/knowledge/mound/curation/status`

GET /api/v1/knowledge/mound/curation/status

### `GET` `/api/v1/knowledge/mound/curation/run`

GET /api/v1/knowledge/mound/curation/run

### `POST` `/api/v1/knowledge/mound/curation/run` 🔒

POST /api/v1/knowledge/mound/curation/run

### `GET` `/api/v1/knowledge/mound/curation/history`

GET /api/v1/knowledge/mound/curation/history

### `GET` `/api/v1/knowledge/mound/curation/scores`

GET /api/v1/knowledge/mound/curation/scores

### `GET` `/api/v1/knowledge/mound/curation/tiers`

GET /api/v1/knowledge/mound/curation/tiers

### `GET` `/api/v1/knowledge/mound/contradictions/detect`

GET /api/v1/knowledge/mound/contradictions/detect

### `POST` `/api/v1/knowledge/mound/contradictions/detect` 🔒

POST /api/v1/knowledge/mound/contradictions/detect

### `GET` `/api/v1/knowledge/mound/contradictions`

GET /api/v1/knowledge/mound/contradictions

### `GET` `/api/v1/knowledge/mound/contradictions/stats`

GET /api/v1/knowledge/mound/contradictions/stats

### `GET` `/api/v1/knowledge/mound/governance/roles` 🔒

GET /api/v1/knowledge/mound/governance/roles

### `POST` `/api/v1/knowledge/mound/governance/roles` 🔒

POST /api/v1/knowledge/mound/governance/roles

### `POST` `/api/v1/knowledge/mound/governance/roles/assign` 🔒

POST /api/v1/knowledge/mound/governance/roles/assign

### `POST` `/api/v1/knowledge/mound/governance/roles/revoke` 🔒

POST /api/v1/knowledge/mound/governance/roles/revoke

### `GET` `/api/v1/knowledge/mound/governance/permissions`

GET /api/v1/knowledge/mound/governance/permissions

### `POST` `/api/v1/knowledge/mound/governance/permissions/check` 🔒

Check authentication and return error response if failed

### `GET` `/api/v1/knowledge/mound/governance/audit` 🔒

GET /api/v1/knowledge/mound/governance/audit

### `GET` `/api/v1/knowledge/mound/governance/audit/user`

GET /api/v1/knowledge/mound/governance/audit/user

### `GET` `/api/v1/knowledge/mound/governance/stats` 🔒

GET /api/v1/knowledge/mound/governance/stats

### `GET` `/api/v1/knowledge/mound/analytics/coverage`

GET /api/v1/knowledge/mound/analytics/coverage

### `GET` `/api/v1/knowledge/mound/analytics/usage`

GET /api/v1/knowledge/mound/analytics/usage

### `GET` `/api/v1/knowledge/mound/analytics/usage/record`

GET /api/v1/knowledge/mound/analytics/usage/record

### `POST` `/api/v1/knowledge/mound/analytics/usage/record` 🔒

POST /api/v1/knowledge/mound/analytics/usage/record

### `GET` `/api/v1/knowledge/mound/analytics/quality/snapshot`

GET /api/v1/knowledge/mound/analytics/quality/snapshot

### `POST` `/api/v1/knowledge/mound/analytics/quality/snapshot` 🔒

POST /api/v1/knowledge/mound/analytics/quality/snapshot

### `GET` `/api/v1/knowledge/mound/analytics/quality/trend`

GET /api/v1/knowledge/mound/analytics/quality/trend

### `GET` `/api/v1/knowledge/mound/analytics/stats`

GET /api/v1/knowledge/mound/analytics/stats

### `GET` `/api/v1/knowledge/mound/extraction/debate`

GET /api/v1/knowledge/mound/extraction/debate

### `POST` `/api/v1/knowledge/mound/extraction/debate` 🔒

POST /api/v1/knowledge/mound/extraction/debate

### `GET` `/api/v1/knowledge/mound/extraction/promote`

GET /api/v1/knowledge/mound/extraction/promote

### `POST` `/api/v1/knowledge/mound/extraction/promote` 🔒

POST /api/v1/knowledge/mound/extraction/promote

### `GET` `/api/v1/knowledge/mound/extraction/stats`

GET /api/v1/knowledge/mound/extraction/stats

### `GET` `/api/v1/knowledge/mound/confidence/decay`

GET /api/v1/knowledge/mound/confidence/decay

### `POST` `/api/v1/knowledge/mound/confidence/decay` 🔒

POST /api/v1/knowledge/mound/confidence/decay

### `GET` `/api/v1/knowledge/mound/confidence/event`

GET /api/v1/knowledge/mound/confidence/event

### `POST` `/api/v1/knowledge/mound/confidence/event` 🔒

POST /api/v1/knowledge/mound/confidence/event

### `GET` `/api/v1/knowledge/mound/confidence/history`

GET /api/v1/knowledge/mound/confidence/history

### `GET` `/api/v1/knowledge/mound/confidence/stats`

GET /api/v1/knowledge/mound/confidence/stats

### `GET` `/api/v1/knowledge/mound/culture/documents`

GET /api/v1/knowledge/mound/culture/documents

### `POST` `/api/v1/knowledge/mound/culture/documents` 🔒

POST /api/v1/knowledge/mound/culture/documents

### `GET` `/api/v1/knowledge/mound/culture/promote`

GET /api/v1/knowledge/mound/culture/promote

### `POST` `/api/v1/knowledge/mound/culture/promote` 🔒

POST /api/v1/knowledge/mound/culture/promote

### `GET` `/api/v1/km/checkpoints` 🔒

GET /api/v1/km/checkpoints

### `POST` `/api/v1/km/checkpoints` 🔒

POST /api/v1/km/checkpoints

---

## Consensus

Consensus Memory endpoint handlers.

### `GET` `/api/consensus/similar`

Find debates similar to a topic

### `GET` `/api/consensus/settled`

Get high-confidence settled topics

### `GET` `/api/consensus/stats`

Get consensus memory statistics

### `GET` `/api/consensus/dissents`

Get recent dissenting views

### `GET` `/api/consensus/contrarian-views`

Get contrarian perspectives

### `GET` `/api/consensus/risk-warnings`

Get risk warnings and edge cases

### `GET` `/api/consensus/domain/:domain` 🔒

Get domain-specific history

---

## Insights

Insights-related endpoint handlers.

### `GET` `/api/insights/recent`

Get recent insights from InsightStore

### `POST` `/api/insights/extract-detailed` 🔒

Extract detailed insights from content

---

## Learning

Cross-cycle learning analytics endpoint handlers.

### `GET` `/api/learning/cycles`

Get all cycle summaries

### `GET` `/api/learning/patterns`

Get learned patterns across cycles

### `GET` `/api/learning/agent-evolution`

Get agent performance evolution

### `GET` `/api/learning/insights`

Get aggregated insights from cycles

---

## Memory

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

### `DELETE` `/api/v1/memory/continuum/{id}`

Delete a memory by ID

### `GET` `/api/v1/memory/tiers` 🔒

List all memory tiers with detailed stats

### `GET` `/api/v1/memory/search` 🔒

Search memories across tiers

### `GET` `/api/v1/memory/critiques` 🔒

Browse critique store entries

---

## Memory Analytics

Memory analytics endpoint handlers.

### `POST` `/api/v1/memory/analytics/snapshot`

Take a manual snapshot

---

## Handler

Operational metrics endpoint handlers.

### `GET` `/api/metrics`

Get operational metrics for monitoring

### `GET` `/api/metrics/health`

Detailed health check

### `GET` `/api/metrics/cache`

Cache statistics

### `GET` `/api/metrics/system`

System information

### `GET` `/metrics`

Prometheus-format metrics (OpenMetrics)

---

## Metrics Endpoint

Unified Prometheus metrics endpoint.

### `GET` `/metrics`

Full Prometheus-format metrics export

### `GET` `/api/v1/metrics/prometheus`

Same as /metrics with API versioning

### `GET` `/api/v1/metrics/prometheus/summary`

Aggregated metrics summary

---

## Devices

Device Registration and Notification API Handlers.

### `POST` `/api/devices/register` 🔒

Register a device for push notifications

### `DELETE` `/api/devices/{device_id}` 🔒

Unregister a device

### `GET` `/api/devices/health` 🔒

Get device connector health

### `POST` `/api/devices/alexa/webhook`

Alexa skill webhook

### `POST` `/api/devices/google/webhook`

Google Actions webhook

---

## NotificationHistory

Handler for notification history and delivery stats.

### `GET` `/api/v1/notifications/history`

Get paginated notification history

### `GET` `/api/v1/notifications/delivery-stats`

GET /api/v1/notifications/delivery-stats

---

## NotificationPreferences

Handler for notification preferences.

### `PUT` `/api/v1/notifications/preferences`

Get notification preferences for current user

---

## NotificationTemplates

CRUD handler for per-user notification templates.

### `GET` `/api/v1/notifications/templates`

GET /api/v1/notifications/templates

### `GET` `/api/v1/notifications/templates/{id}`

GET /api/v1/notifications/templates/{id}

### `PUT` `/api/v1/notifications/templates/{id}`

PUT /api/v1/notifications/templates/{id}

### `POST` `/api/v1/notifications/templates/{id}/reset`

POST /api/v1/notifications/templates/{id}/reset

### `POST` `/api/v1/notifications/templates/{id}/preview`

POST /api/v1/notifications/templates/{id}/preview

---

## Oauth Wizard

Unified OAuth Wizard Handler for SME Onboarding.

### `GET` `/api/v2/integrations/wizard`

Get wizard configuration

### `GET` `/api/v2/integrations/wizard/providers`

List all available providers

### `GET` `/api/v2/integrations/wizard/status`

Get status of all integrations

### `POST` `/api/v2/integrations/wizard/validate`

Validate configuration before connecting

---

## Crashes

Frontend crash telemetry collector.

### `POST` `/api/observability/crashes`

Ingest crash reports

### `GET` `/api/observability/crashes` 🔒

List recent crashes (admin)

### `GET` `/api/observability/crashes/stats` 🔒

Crash frequency stats (admin)

---

## Dashboard

Observability dashboard endpoint.

### `GET` `/api/observability/dashboard` 🔒

Aggregated system observability metrics

---

## EndpointAnalytics

Handler for API endpoint performance analytics.

### `GET` `/api/analytics/endpoints`

GET /api/analytics/endpoints - List all endpoints with metrics

### `GET` `/api/analytics/endpoints/slowest`

GET /api/analytics/endpoints/slowest - Top N slowest endpoints

### `GET` `/api/analytics/endpoints/errors`

GET /api/analytics/endpoints/errors - Top N endpoints by error rate

### `GET` `/api/analytics/endpoints/health`

GET /api/analytics/endpoints/health - Overall API health summary

---

## Slo

SLO (Service Level Objective) endpoint handlers.

### `GET` `/api/slos/status`

Overall SLO compliance status

### `GET` `/api/slos/error-budget`

Error budget timeline

### `GET` `/api/slos/violations`

Recent SLO violations

### `GET` `/api/slos/targets`

Configured SLO targets

### `GET` `/api/v1/slos/status`

Versioned endpoint

### `GET` `/api/v1/slo/status`

SLO enforcer real-time compliance status

### `GET` `/api/v1/slo/budget`

SLO enforcer error budget remaining

### `GET` `/api/health/slos`

Debate SLO health (green/yellow/red per SLO, multi-window)

---

## Gateway

HTTP Handlers for OpenClaw Gateway.

### `GET` `/api/gateway/openclaw/health`

Gateway health

### `GET` `/api/gateway/openclaw/metrics`

Gateway metrics

### `GET` `/api/gateway/openclaw/audit`

Audit log

---

## Coordination

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

### `GET` `/api/v1/coordination/health`

GET /api/v1/coordination/health -- health check

---

## Handler

Unified Orchestration Handler for Aragora Control Plane.

### `POST` `/api/v1/orchestration/deliberate`

Unified vetted decisionmaking endpoint

### `GET` `/api/v1/orchestration/status/:id` 🔒

Get vetted decisionmaking status

### `GET` `/api/v1/orchestration/templates` 🔒

List available templates

### `POST` `/api/v1/orchestration/deliberate/sync`

Synchronous vetted decisionmaking

---

## PaymentRoutes

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

## Decomposition

Handler for task decomposition visualization endpoints.

### `GET` `/api/v1/pipeline` 🔒

GET /api/v1/pipeline

### `POST` `/api/v1/pipeline` 🔒

POST /api/v1/pipeline

---

## PipelineExecute

Handler for pipeline execution via self-improvement pipeline.

### `GET` `/api/v1/pipeline` 🔒

Execute pipeline goals via the canonical DecisionPlan runtime

### `POST` `/api/v1/pipeline` 🔒

Execute pipeline goals via the canonical DecisionPlan runtime

---

## Pipeline Graph

Universal Pipeline Graph REST Handler.

### `POST` `/api/v1/pipeline/graph`

Create graph

### `GET` `/api/v1/pipeline/graph`

List graphs

### `GET` `/api/v1/pipeline/graph/{id}`

Get graph

### `DELETE` `/api/v1/pipeline/graph/{id}`

Delete graph

### `POST` `/api/v1/pipeline/graph/{id}/node`

Add node

### `DELETE` `/api/v1/pipeline/graph/{id}/node/{nid}`

Remove node

### `GET` `/api/v1/pipeline/graph/{id}/nodes`

Query nodes (stage/subtype filters)

### `POST` `/api/v1/pipeline/graph/{id}/promote`

Promote nodes to next stage

### `GET` `/api/v1/pipeline/graph/{id}/provenance/{nid}`

Provenance chain

### `GET` `/api/v1/pipeline/graph/{id}/suggestions`

Transition suggestions

### `GET` `/api/v1/pipeline/graph/{id}/react-flow`

React Flow JSON export

### `GET` `/api/v1/pipeline/graph/{id}/integrity`

Integrity hash

### `POST` `/api/v1/pipeline/graph/{id}/node/{nid}/reassign`

Reassign agent on node

---

## PlanManagement

Handler for decision plan management endpoints.

### `PUT` `/api/v1/plans`

Get plans from context or in-memory store

---

## ProvenanceExplorer

Handler for provenance explorer endpoints (singular /graph/ prefix).

### `GET` `/api/v1/pipeline/graph`

GET /api/v1/pipeline/graph

### `POST` `/api/v1/pipeline/graph`

POST /api/v1/pipeline/graph

---

## Receipts

Receipt Explorer API Handler for Pipeline Execution Receipts.

### `GET` `/api/v1/receipts`

List receipts with filtering

---

## PipelineTransitions

Handler for AI stage transition endpoints.

### `POST` `/api/v1/pipeline/transitions`

POST /api/v1/pipeline/transitions

---

## UniversalGraph

Handler for universal pipeline graph endpoints.

### `POST` `/api/v1/pipeline/graphs`

POST /api/v1/pipeline/graphs

### `PUT` `/api/v1/pipeline/graphs`

PUT /api/v1/pipeline/graphs

### `PATCH` `/api/v1/pipeline/graphs`

PATCH /api/v1/pipeline/graphs

### `DELETE` `/api/v1/pipeline/graphs`

DELETE /api/v1/pipeline/graphs

---

## Platform Config

Platform Configuration handler.

### `GET` `/api/v1/platform/config` 🔒

Full platform configuration

---

## Handler

Prompt Engine API Handler.

### `GET` `/api/prompt-engine/runs` 🔒

List persisted backbone runs

### `GET` `/api/prompt-engine/runs/{id}` 🔒

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

## Gallery

Public Gallery endpoint handlers.

### `GET` `/api/gallery`

List public debates

---

## StatusPage

Handler for public status page endpoints.

### `GET` `/status`

Return detailed component status

### `GET` `/api/status`

Return detailed component status

### `GET` `/api/status/summary`

Return JSON status summary

### `GET` `/api/status/history`

Return historical uptime data

### `GET` `/api/status/components`

Check health of all components

### `GET` `/api/status/incidents`

Return current and recent incidents

### `GET` `/api/v1/status`

Return detailed component status

### `GET` `/api/v1/status/components`

Check health of all components

### `GET` `/api/v1/status/incidents`

Return current and recent incidents

### `GET` `/api/v1/status/uptime`

Format uptime in human-readable form

### `GET` `/api/v1/public/surfaces`

Summarize the exposed surface inventory by readiness

---

## Security Debate

Security Debate API endpoint handlers.

### `POST` `/api/v1/audit/security/debate`

Trigger a security debate on findings

---

## Threat Intel

Threat Intelligence API Handlers.

### `POST` `/api/v1/threat/url` 🔒

Check URL for threats

### `POST` `/api/v1/threat/urls` 🔒

Batch check URLs

### `GET` `/api/v1/threat/ip/{ip_address}` 🔒

Check IP reputation

### `POST` `/api/v1/threat/ips` 🔒

Batch check IPs

### `GET` `/api/v1/threat/hash/{hash_value}` 🔒

Check file hash reputation

### `POST` `/api/v1/threat/hashes` 🔒

Batch check hashes

### `POST` `/api/v1/threat/email` 🔒

Scan email content

### `GET` `/api/v1/threat/status` 🔒

Get service status

---

## SharedInbox

HTTP handler for shared inbox endpoints.

### `GET` `/api/v1/inbox/shared` 🔒

GET /api/v1/inbox/shared

### `POST` `/api/v1/inbox/shared` 🔒

POST /api/v1/inbox/shared

### `GET` `/api/v1/inbox/routing/rules` 🔒

GET /api/v1/inbox/routing/rules

### `POST` `/api/v1/inbox/routing/rules` 🔒

POST /api/v1/inbox/routing/rules

---

## Feedback

User Feedback Collection Handler.

### `GET` `/api/v1/feedback/nps/summary`

Get NPS summary (requires feedback.update - admin)

### `GET` `/api/v1/feedback/prompts`

Get active feedback prompts (requires feedback.read)

---

## Onboarding

Onboarding Orchestration Handler.

### `GET` `/api/v1/onboarding/flow`

Get current onboarding state

### `POST` `/api/v1/onboarding/flow`

Initialize onboarding

### `PUT` `/api/v1/onboarding/flow/step`

Update current step

### `GET` `/api/v1/onboarding/templates`

Get recommended starter templates

### `POST` `/api/v1/onboarding/first-debate`

Start guided first debate

### `POST` `/api/v1/onboarding/quick-start`

Apply quick-start configuration

### `GET` `/api/v1/onboarding/analytics`

Get onboarding funnel analytics

---

## ReadinessCheck

Public endpoint reporting what a user needs to configure before

### `GET` `/api/v1/readiness`

GET /api/v1/readiness

### `GET` `/api/readiness`

GET /api/readiness

---

## SMEUsageDashboard

Handler for SME usage dashboard endpoints.

### `GET` `/api/v1/usage/summary`

Get unified usage summary for the SME dashboard

### `GET` `/api/v1/usage/breakdown`

Get detailed usage breakdown by dimension

### `GET` `/api/v1/usage/roi`

Get ROI analysis for the organization

### `GET` `/api/v1/usage/export`

Export usage data in various formats

### `GET` `/api/v1/usage/budget-status`

GET /api/v1/usage/budget-status

### `GET` `/api/v1/usage/forecast`

Get usage forecast based on current patterns

### `GET` `/api/v1/usage/benchmarks`

Get industry benchmark comparison data

---

## ChannelHealth

Handler for chat channel health monitoring.

### `GET` `/api/v1/channels/health`

Get basic health info for connectors without get_health method

### `GET` `/api/v1/channels/{channel}/health`

Get basic health info for connectors without get_health method

---

## Collaboration

Handler for social collaboration endpoints.

### `GET` `/api/v1/social/collaboration/sessions` 🔒

GET /api/v1/social/collaboration/sessions

---

## Discord Oauth

Discord OAuth Handler for bot installation flow.

### `GET` `/api/integrations/discord/install`

Redirect to Discord OAuth

### `GET` `/api/integrations/discord/callback`

Handle OAuth callback

### `POST` `/api/integrations/discord/uninstall`

Handle guild removal

---

## Notifications

Handler for notification-related endpoints.

### `GET` `/api/v1/notifications/status`

Get status of notification integrations scoped to organization

### `GET` `/api/v1/notifications/email/recipients`

Get list of email recipients scoped to organization

### `POST` `/api/v1/notifications/email/config`

Configure email integration settings for an organization

### `POST` `/api/v1/notifications/telegram/config`

Configure email integration settings for an organization

### `POST` `/api/v1/notifications/email/recipient`

Add an email recipient for an organization

### `DELETE` `/api/v1/notifications/email/recipient`

Add an email recipient for an organization

### `POST` `/api/v1/notifications/test`

Send a test notification

### `POST` `/api/v1/notifications/send`

Send a notification with custom content

---

## Relationship

Relationship endpoint handlers.

### `GET` `/api/relationships/summary`

Global relationship overview

### `GET` `/api/relationships/graph`

Full relationship graph for visualizations

### `GET` `/api/relationships/stats`

Relationship system statistics

### `GET` `/api/relationship/{agent_a}/{agent_b}`

Detailed relationship between two agents

---

## Slack Oauth

Slack OAuth Handler for app installation flow.

### `GET` `/api/integrations/slack/install`

Redirect to Slack OAuth

### `GET` `/api/integrations/slack/callback`

Handle OAuth callback

### `POST` `/api/integrations/slack/uninstall`

Handle app removal

---

## Social Media

Social Media endpoint handlers for Twitter and YouTube.

### `GET` `/api/youtube/auth`

Get YouTube OAuth authorization URL

### `GET` `/api/youtube/callback`

Handle YouTube OAuth callback

### `GET` `/api/youtube/status`

Get YouTube connector status

### `POST` `/api/debates/{id}/publish/twitter` 🔒

Publish debate to Twitter/X

### `POST` `/api/debates/{id}/publish/youtube` 🔒

Publish debate to YouTube

---

## Teams Oauth

Microsoft Teams OAuth Handler for app installation flow.

### `GET` `/api/integrations/teams/install`

Redirect to Microsoft OAuth

### `GET` `/api/integrations/teams/callback`

Handle OAuth callback

### `POST` `/api/integrations/teams/refresh`

Refresh expired tokens

---

## Spectate Ws

WebSocket/SSE handler for real-time spectate events.

### `GET` `/api/v1/spectate/recent`

Get recent buffered spectate events

### `GET` `/api/v1/spectate/status`

Get bridge status (active, subscribers, buffer size)

### `GET` `/api/v1/spectate/stream`

Live SSE on the unified server, JSON/snapshot fallback here

---

## TaskExecution

HTTP handler for task execution endpoints.

### `POST` `/api/v2/tasks`

List tasks, optionally filtered by status

---

## TaskQueue

Expose queue inspection plus lease-scoped lifecycle endpoints.

### `GET` `/api/v1/tasks/queue` 🔒

GET /api/v1/tasks/queue

### `GET` `/api/v1/tasks/queue/stats` 🔒

GET /api/v1/tasks/queue/stats

### `POST` `/api/v1/tasks/queue/sync` 🔒

POST /api/v1/tasks/queue/sync

### `GET` `/api/v1/tasks/queue/{task_id}` 🔒

GET /api/v1/tasks/queue/{task_id}

### `POST` `/api/v1/tasks/queue/{task_id}/claim` 🔒

POST /api/v1/tasks/queue/{task_id}/claim

### `GET` `/api/v1/tasks/leases` 🔒

GET /api/v1/tasks/leases

### `POST` `/api/v1/tasks/leases/{lease_id}/heartbeat` 🔒

POST /api/v1/tasks/leases/{lease_id}/heartbeat

### `POST` `/api/v1/tasks/leases/{lease_id}/release` 🔒

POST /api/v1/tasks/leases/{lease_id}/release

### `POST` `/api/v1/tasks/leases/{lease_id}/complete` 🔒

POST /api/v1/tasks/leases/{lease_id}/complete

### `GET` `/api/v1/tasks/salvage` 🔒

GET /api/v1/tasks/salvage

---

## Benchmarking

Handler for decision benchmarking endpoints.

### `GET` `/api/benchmarks`

GET /api/v1/benchmarks -- list aggregated benchmarks for a category

### `GET` `/api/benchmarks/categories`

GET /api/v1/benchmarks/categories -- list available benchmark categories

### `GET` `/api/benchmarks/compare`

GET /api/v1/benchmarks/compare -- compare tenant metrics to benchmarks

---

## Evaluation

Handler for LLM-as-Judge evaluation endpoints.

### `POST` `/api/v1/evaluate`

Evaluate a response using LLM-as-Judge

### `POST` `/api/v1/evaluate/compare`

Compare two responses using pairwise evaluation

### `POST` `/api/v1/evaluate/dimensions`

List available evaluation dimensions

### `POST` `/api/v1/evaluate/profiles`

List available evaluation weight profiles

---

## Verification

Formal verification endpoint handlers.

### `GET` `/api/verification/status`

Get status of formal verification backends

### `POST` `/api/verification/formal-verify` 🔒

Verify a claim using Z3 SMT solver

---

## Voice

Handler for Twilio Voice webhooks.

### `GET` `/api/v1/voice/inbound`

GET /api/v1/voice/inbound

### `GET` `/api/v1/voice/status`

GET /api/v1/voice/status

### `GET` `/api/v1/voice/gather`

GET /api/v1/voice/gather

### `GET` `/api/v1/voice/gather/confirm`

GET /api/v1/voice/gather/confirm

### `GET` `/api/v1/voice/device`

GET /api/v1/voice/device

### `GET` `/api/v1/voice/synthesize`

GET /api/v1/voice/synthesize

### `GET` `/api/v1/voice/voices`

GET /api/v1/voice/voices

### `GET` `/api/v1/voice/sessions`

GET /api/v1/voice/sessions

### `GET` `/api/v1/voice/sessions/{session_id}`

GET /api/v1/voice/sessions/{session_id}

### `GET` `/api/v1/voice/config`

GET /api/v1/voice/config

### `GET` `/api/voice/inbound`

GET /api/voice/inbound

### `GET` `/api/voice/status`

GET /api/voice/status

### `GET` `/api/voice/gather`

GET /api/voice/gather

### `GET` `/api/voice/gather/confirm`

GET /api/voice/gather/confirm

---

## Webhook

Handler for webhook management API endpoints.

### `GET` `/api/v1/webhooks` 🔒

Handle GET /api/webhooks - list all webhooks

### `POST` `/api/v1/webhooks` 🔒

Handle GET /api/webhooks - list all webhooks

### `GET` `/api/v1/webhooks/events`

Handle GET /api/webhooks/events - list available event types

### `POST` `/api/v1/webhooks/events/categories`

POST /api/v1/webhooks/events/categories

### `GET` `/api/v1/webhooks/slo/status` 🔒

Handle GET /api/webhooks/slo/status - get SLO webhook status

### `POST` `/api/v1/webhooks/slo/test` 🔒

Handle POST /api/webhooks/slo/test - send test SLO violation notification

### `GET` `/api/v1/webhooks/dead-letter` 🔒

GET /api/v1/webhooks/dead-letter

### `GET` `/api/v1/webhooks/queue/stats` 🔒

Handle GET /api/webhooks/queue/stats - get queue statistics

### `POST` `/api/v1/webhooks/bulk`

POST /api/v1/webhooks/bulk

### `POST` `/api/v1/webhooks/pause-all`

POST /api/v1/webhooks/pause-all

### `POST` `/api/v1/webhooks/resume-all`

POST /api/v1/webhooks/resume-all

---

## WorkflowBuilder

HTTP handlers for visual workflow builder API.

### `POST` `/api/v1/workflows/generate`

Generate a workflow from a natural language description

### `POST` `/api/v1/workflows/auto-layout`

POST /api/v1/workflows/auto-layout

### `POST` `/api/v1/workflows/step-types`

POST /api/v1/workflows/step-types

### `POST` `/api/v1/workflows/from-pattern`

POST /api/v1/workflows/from-pattern

### `POST` `/api/v1/workflows/validate`

Validate a workflow definition

---

## Workflow

HTTP request handler for workflow API endpoints.

### `GET` `/api/v1/workflows`

Handle GET /api/workflows

### `POST` `/api/v1/workflows`

Handle GET /api/workflows

### `GET` `/api/v1/workflow-templates`

GET /api/v1/workflow-templates

### `GET` `/api/v1/workflows/templates`

Handle GET /api/workflow-templates

### `POST` `/api/v1/workflows/templates`

Handle GET /api/workflow-templates

### `DELETE` `/api/v1/workflows/templates`

Handle GET /api/workflow-templates

### `GET` `/api/v1/workflow-approvals` 🔒

GET /api/v1/workflow-approvals

### `GET` `/api/v1/workflow-executions`

GET /api/v1/workflow-executions

### `GET` `/api/v1/workflows/executions`

Handle GET /api/workflow-executions

### `POST` `/api/v1/workflows/executions`

Handle GET /api/workflow-executions

### `DELETE` `/api/v1/workflows/executions`

Handle GET /api/workflow-executions

---

## TemplateRegistry

HTTP handler for the public template registry API.

### `POST` `/api/v1/templates/registry`

Extract listing ID from path like /api/v1/templates/registry/{id}

---

## Workspace Module

Workspace Handler - Enterprise Privacy and Data Isolation APIs.

### `POST` `/api/workspaces` 🔒

Create a new workspace

### `GET` `/api/workspaces` 🔒

List workspaces

### `GET` `/api/workspaces/{id}` 🔒

Get workspace details

### `DELETE` `/api/workspaces/{id}` 🔒

Delete workspace

### `POST` `/api/workspaces/{id}/members` 🔒

Add member to workspace

### `GET` `/api/retention/policies` 🔒

List retention policies

### `POST` `/api/retention/policies` 🔒

Create retention policy

### `POST` `/api/retention/policies/{id}/execute` 🔒

Execute retention policy

### `GET` `/api/retention/expiring` 🔒

Get items expiring soon

### `POST` `/api/classify` 🔒

Classify content sensitivity

### `GET` `/api/classify/policy/{level}` 🔒

Get policy for sensitivity level

### `GET` `/api/audit/entries` 🔒

Query audit entries

### `GET` `/api/audit/report` 🔒

Generate compliance report

### `GET` `/api/audit/verify` 🔒

Verify audit log integrity

---

## Authentication

Endpoints marked with 🔒 require authentication.

Include an `Authorization` header with your API token:

```
Authorization: Bearer <your-api-token>
```

Set `ARAGORA_API_TOKEN` environment variable to configure the token.

---

*Generated automatically by `scripts/generate_api_docs.py`*
