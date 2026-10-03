# Aragora API Documentation

This document describes the HTTP API endpoints provided by the Aragora server.

## Table of Contents

- [A2A](#a2a)
- [Accounting](#accounting)
- [AgentBridge](#agentbridge)
- [Agent Evolution Dashboard](#agent-evolution-dashboard)
- [AnalyticsMetrics](#analyticsmetrics)
- [AnalyticsPerformance](#analyticsperformance)
- [Ap Automation](#ap-automation)
- [ApiDocs](#apidocs)
- [UnifiedApprovals](#unifiedapprovals)
- [Ar Automation](#ar-automation)
- [Audience Suggestions](#audience-suggestions)
- [Audit Export](#audit-export)
- [Audit Trail](#audit-trail)
- [Auditing](#auditing)
- [Autonomous Learning](#autonomous-learning)
- [Backup Handler](#backup-handler)
- [Backup Offsite Handler](#backup-offsite-handler)
- [Belief](#belief)
- [Benchmarking](#benchmarking)
- [Bindings](#bindings)
- [Breakpoints](#breakpoints)
- [Budgets](#budgets)
- [CanvasPipeline](#canvaspipeline)
- [Checkpoints](#checkpoints)
- [Cloud Storage](#cloud-storage)
- [Code Review](#code-review)
- [Compliance](#compliance)
- [Composite](#composite)
- [ComputerUse](#computeruse)
- [Consensus](#consensus)
- [Context Budget](#context-budget)
- [Coordination](#coordination)
- [Critique](#critique)
- [Cross Pollination](#cross-pollination)
- [DAGOperations](#dagoperations)
- [Dashboard](#dashboard)
- [Data Classification Handler](#data-classification-handler)
- [Debate Intervention](#debate-intervention)
- [Debate Stats](#debate-stats)
- [Decision](#decision)
- [DecisionAnalytics](#decisionanalytics)
- [Deliberations](#deliberations)
- [Dependency Analysis](#dependency-analysis)
- [Devices](#devices)
- [Differentiation](#differentiation)
- [Docs](#docs)
- [Dr Handler](#dr-handler)
- [EmailDebate](#emaildebate)
- [Email Services](#email-services)
- [EmailTriage](#emailtriage)
- [EndpointAnalytics](#endpointanalytics)
- [ERC8004](#erc8004)
- [Evaluation](#evaluation)
- [Expenses](#expenses)
- [Explainability](#explainability)
- [External Agents](#external-agents)
- [External Integrations](#external-integrations)
- [Feature Flags](#feature-flags)
- [Feedback](#feedback)
- [Feedback Hub](#feedback-hub)
- [Gallery](#gallery)
- [Gastown Dashboard](#gastown-dashboard)
- [GatewayAgents](#gatewayagents)
- [GatewayConfig](#gatewayconfig)
- [GatewayCredentials](#gatewaycredentials)
- [Gateway](#gateway)
- [GatewayHealth](#gatewayhealth)
- [Gdpr Deletion](#gdpr-deletion)
- [Genesis](#genesis)
- [Harnesses](#harnesses)
- [HybridDebate](#hybriddebate)
- [IdeaCanvas](#ideacanvas)
- [Inbox Command](#inbox-command)
- [Integration Management](#integration-management)
- [Introspection](#introspection)
- [Invoices](#invoices)
- [KnowledgeChat](#knowledgechat)
- [Knowledge Flow](#knowledge-flow)
- [Laboratory](#laboratory)
- [Marketplace](#marketplace)
- [MarketplaceBrowse](#marketplacebrowse)
- [Marketplace Pilot](#marketplace-pilot)
- [MCPTools](#mcptools)
- [Memory Unified](#memory-unified)
- [Metrics Endpoint](#metrics-endpoint)
- [Ml](#ml)
- [Moderation](#moderation)
- [ModerationAnalytics](#moderationanalytics)
- [Moments](#moments)
- [Nomic](#nomic)
- [Oauth Wizard](#oauth-wizard)
- [Onboarding](#onboarding)
- [OpenClawGateway](#openclawgateway)
- [OperatorIntervention](#operatorintervention)
- [Organizations](#organizations)
- [OutcomeAnalytics](#outcomeanalytics)
- [Outcome Dashboard](#outcome-dashboard)
- [Partner](#partner)
- [Persona](#persona)
- [Pipeline Graph](#pipeline-graph)
- [Pipeline Telemetry](#pipeline-telemetry)
- [Plans](#plans)
- [Platform Config](#platform-config)
- [Playbook](#playbook)
- [Playground](#playground)
- [Policy](#policy)
- [Privacy](#privacy)
- [Queue](#queue)
- [RalphDashboard](#ralphdashboard)
- [RBAC](#rbac)
- [ReadinessCheck](#readinesscheck)
- [Receipts](#receipts)
- [Replays](#replays)
- [Repository](#repository)
- [ReviewQueue](#reviewqueue)
- [Reviews](#reviews)
- [RLMContext](#rlmcontext)
- [Runs](#runs)
- [Sandbox](#sandbox)
- [SCIM](#scim)
- [Security Debate](#security-debate)
- [Selection](#selection)
- [Self Improve](#self-improve)
- [Self Improve Details](#self-improve-details)
- [Settlement](#settlement)
- [Skill Marketplace](#skill-marketplace)
- [Skills](#skills)
- [Slack](#slack)
- [Slo](#slo)
- [SMESuccessDashboard](#smesuccessdashboard)
- [SMEUsageDashboard](#smeusagedashboard)
- [Spectate Ws](#spectate-ws)
- [SpendAnalytics](#spendanalytics)
- [SpendAnalyticsDashboard](#spendanalyticsdashboard)
- [SSO](#sso)
- [Status Page](#status-page)
- [System Health](#system-health)
- [System Intelligence](#system-intelligence)
- [TemplateDiscovery](#templatediscovery)
- [Template Marketplace](#template-marketplace)
- [Threat Intel](#threat-intel)
- [Tournaments](#tournaments)
- [Training](#training)
- [Transcription](#transcription)
- [Uncertainty](#uncertainty)
- [UsageMetering](#usagemetering)
- [Verticals](#verticals)
- [Visualization](#visualization)
- [Webhook](#webhook)
- [Workflow Templates](#workflow-templates)
- [Workspace Module](#workspace-module)
- [Intelligence](#intelligence)
- [Metrics](#metrics)
- [Quick Scan](#quick-scan)
- [Audit Bridge](#audit-bridge)
- [Pr Review](#pr-review)

---

## A2A

A2A Protocol HTTP Handler.

### `GET` `/api/a2a/agents`

List all available agents

### `GET` `/api/a2a/agents/:name`

Get agent card by name

### `POST` `/api/a2a/tasks`

Submit a task

### `GET` `/api/a2a/tasks/:id`

Get task status

### `DELETE` `/api/a2a/tasks/:id`

Cancel task

### `POST` `/api/a2a/tasks/:id/stream`

Stream task (WebSocket upgrade)

### `GET` `/api/a2a/.well-known/agent.json`

Discovery endpoint

---

## Accounting

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

### `GET` `/api/accounting/gusto/payrolls/{payroll_id}`

Payroll run details

### `POST` `/api/accounting/gusto/payrolls/{payroll_id}/journal-entry`

Generate journal entry

---

## AgentBridge

Expose persisted agent-bridge state and feature-gated operator writes.

### `GET` `/api/v1/agent-bridge/runs`

GET /api/v1/agent-bridge/runs

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

## AnalyticsMetrics

Handler for analytics metrics dashboard endpoints.

### `GET` `/api/analytics/debates/overview` 🔒

Get debate overview statistics

### `GET` `/api/analytics/debates/trends` 🔒

Get agent performance trends over time

### `GET` `/api/analytics/debates/topics` 🔒

Get topic distribution for debates

### `GET` `/api/analytics/debates/outcomes` 🔒

Get debate outcome distribution (win/loss/draw)

### `GET` `/api/analytics/agents/leaderboard` 🔒

Get agent leaderboard with ELO rankings and win rates

### `GET` `/api/analytics/agents/comparison` 🔒

Compare multiple agents

### `GET` `/api/analytics/agents/trends` 🔒

Get agent performance trends over time

### `GET` `/api/analytics/usage/tokens` 🔒

Get token consumption trends

### `GET` `/api/analytics/usage/costs` 🔒

Get cost breakdown by provider and model

### `GET` `/api/analytics/usage/active_users` 🔒

Get active user counts

---

## AnalyticsPerformance

Handler for analytics performance endpoints.

### `GET` `/api/analytics/agents/performance` 🔒

Get aggregate agent performance metrics

### `GET` `/api/analytics/debates/summary` 🔒

Get debate summary statistics

### `GET` `/api/analytics/trends`

Calculate trend analysis from data points

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `data_points` | string | List of period data points |

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

## ApiDocs

Handler for API documentation and introspection endpoints.

### `GET` `/api/v1/docs/openapi.json`

GET /api/v1/docs/openapi.json

### `GET` `/api/v1/docs/routes`

Return a lightweight summary of all registered routes

### `GET` `/api/v1/docs/stats`

Return API statistics: endpoint counts by tag and method

---

## UnifiedApprovals

Aggregate approval requests across subsystems.

### `GET` `/api/v1/approvals`

GET /api/v1/approvals

### `GET` `/api/v1/approvals/pending`

GET /api/v1/approvals/pending

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

## Audience Suggestions

Audience suggestion handler for debate audience input.

### `GET` `/api/v1/audience/suggestions`

List clustered suggestions for a debate

### `POST` `/api/v1/audience/suggestions`

Submit a new audience suggestion

---

## Audit Export

Audit Export API Handler.

### `GET` `/api/audit/events`

Query audit events

### `GET` `/api/audit/stats`

Audit log statistics

### `POST` `/api/audit/export`

Export audit log (JSON, CSV, SOC2)

### `POST` `/api/audit/verify`

Verify audit log integrity

---

## Audit Trail

Audit Trail HTTP Handlers for Aragora.

### `GET` `/api/v1/audit-trails`

List recent audit trails

### `GET` `/api/v1/audit-trails/:trail_id`

Get specific audit trail

### `GET` `/api/v1/audit-trails/:trail_id/export`

Export (format=json|csv|md)

### `POST` `/api/v1/audit-trails/:trail_id/verify`

Verify integrity checksum

### `GET` `/api/v1/receipts`

List recent decision receipts

### `GET` `/api/v1/receipts/:receipt_id`

Get specific receipt

### `POST` `/api/v1/receipts/:receipt_id/verify`

Verify receipt integrity

---

## Auditing

Auditing and security analysis endpoint handlers.

### `POST` `/api/debates/capability-probe`

Run capability probes on an agent

### `POST` `/api/debates/deep-audit`

Run deep audit on a task

### `POST` `/api/debates/:id/red-team`

Run red team analysis on a debate

---

## Autonomous Learning

Autonomous Learning Handler for Aragora.

### `GET` `/api/v2/learning/sessions`

List training sessions

### `POST` `/api/v2/learning/sessions`

Start new training session

### `GET` `/api/v2/learning/sessions/:session_id`

Get session details

### `POST` `/api/v2/learning/sessions/:session_id/stop`

Stop training session

### `GET` `/api/v2/learning/metrics`

Get learning metrics

### `GET` `/api/v2/learning/metrics/:metric_type`

Get specific metric

### `POST` `/api/v2/learning/feedback`

Submit learning feedback

### `GET` `/api/v2/learning/patterns`

List detected patterns

### `POST` `/api/v2/learning/patterns/:pattern_id/validate`

Validate a pattern

### `GET` `/api/v2/learning/knowledge`

Get extracted knowledge

### `POST` `/api/v2/learning/knowledge/extract`

Trigger knowledge extraction

### `GET` `/api/v2/learning/recommendations`

Get learning recommendations

### `GET` `/api/v2/learning/performance`

Get model performance stats

### `POST` `/api/v2/learning/calibrate`

Trigger calibration

---

## Backup Handler

Backup HTTP Handlers for Aragora.

### `GET` `/api/v2/backups`

List backups with filters

### `POST` `/api/v2/backups`

Create new backup

### `GET` `/api/v2/backups/:backup_id`

Get specific backup metadata

### `POST` `/api/v2/backups/:backup_id/verify`

Verify backup integrity

### `POST` `/api/v2/backups/:backup_id/verify-comprehensive`

Comprehensive verification

### `POST` `/api/v2/backups/:backup_id/restore-test`

Dry-run restore test

### `DELETE` `/api/v2/backups/:backup_id`

Delete a backup

### `POST` `/api/v2/backups/cleanup`

Run retention policy cleanup

### `GET` `/api/v2/backups/stats`

Backup statistics

---

## Backup Offsite Handler

Backup Offsite and Restore Drill HTTP Handlers.

### `GET` `/api/v1/backup/status`

Current backup status and last successful backup

### `GET` `/api/v1/backup/drills`

List restore drill results

### `POST` `/api/v1/backup/drill`

Trigger a manual restore drill

---

## Belief

Belief Network and Reasoning endpoint handlers.

### `GET` `/api/belief-network/:debate_id/cruxes`

Get key claims that impact debate outcome

### `GET` `/api/belief-network/:debate_id/load-bearing-claims`

Get high-centrality claims

### `GET` `/api/provenance/:debate_id/claims/:claim_id/support`

Get claim verification status

### `GET` `/api/laboratory/emergent-traits`

Get emergent traits from agent performance

### `GET` `/api/debate/:debate_id/graph-stats`

Get argument graph statistics

---

## Benchmarking

Handler for decision benchmarking endpoints.

### `GET` `/api/benchmarks` 🔒

GET /api/v1/benchmarks -- list aggregated benchmarks for a category

### `GET` `/api/benchmarks/categories` 🔒

GET /api/v1/benchmarks/categories -- list available benchmark categories

### `GET` `/api/benchmarks/compare` 🔒

GET /api/v1/benchmarks/compare -- compare tenant metrics to benchmarks

---

## Bindings

Bindings endpoint handlers.

### `GET` `/api/bindings`

List all message bindings

### `GET` `/api/bindings/:provider`

List bindings for a provider

### `POST` `/api/bindings`

Create a new binding

### `PUT` `/api/bindings/:id`

Update a binding

### `DELETE` `/api/bindings/:id`

Remove a binding

### `POST` `/api/bindings/resolve`

Resolve binding for a message

### `GET` `/api/bindings/stats`

Get router statistics

---

## Breakpoints

Breakpoints endpoint handlers for human-in-the-loop intervention.

### `GET` `/api/breakpoints/pending`

List pending breakpoints awaiting resolution

### `POST` `/api/breakpoints/{id}/resolve`

Resolve a pending breakpoint

### `GET` `/api/breakpoints/{id}/status`

Get status of a specific breakpoint

---

## Budgets

Budget Management API Handler.

### `GET` `/api/v1/budgets`

List budgets for org

### `POST` `/api/v1/budgets`

Create a budget

### `GET` `/api/v1/budgets/:id`

Get budget details

### `PATCH` `/api/v1/budgets/:id`

Update a budget

### `DELETE` `/api/v1/budgets/:id`

Delete (close) a budget

### `GET` `/api/v1/budgets/:id/alerts`

Get alerts for a budget

### `POST` `/api/v1/budgets/:id/alerts/:alert_id/acknowledge`

Acknowledge alert

### `POST` `/api/v1/budgets/:id/override`

Add override for user

### `DELETE` `/api/v1/budgets/:id/override/:user_id`

Remove override

### `POST` `/api/v1/budgets/:id/reset`

Reset budget period

### `GET` `/api/v1/budgets/:id/transactions`

Get transaction history

### `GET` `/api/v1/budgets/:id/trends`

Get spending trends for budget

### `GET` `/api/v1/budgets/summary`

Get org budget summary

### `GET` `/api/v1/budgets/trends`

Get org-wide spending trends

### `POST` `/api/v1/budgets/check`

Pre-flight cost check

---

## CanvasPipeline

HTTP handler for the idea-to-execution canvas pipeline.

### `GET` `GET /api/v1/canvas/pipeline`

GET GET /api/v1/canvas/pipeline

### `GET` `POST /api/v1/canvas/pipeline/from-debate`

GET POST /api/v1/canvas/pipeline/from-debate

### `GET` `POST /api/v1/canvas/pipeline/from-ideas`

GET POST /api/v1/canvas/pipeline/from-ideas

### `GET` `POST /api/v1/canvas/pipeline/from-braindump`

GET POST /api/v1/canvas/pipeline/from-braindump

### `GET` `POST /api/v1/canvas/pipeline/from-template`

GET POST /api/v1/canvas/pipeline/from-template

### `GET` `POST /api/v1/canvas/pipeline/demo`

GET POST /api/v1/canvas/pipeline/demo

### `GET` `POST /api/v1/canvas/pipeline/advance`

GET POST /api/v1/canvas/pipeline/advance

### `GET` `POST /api/v1/canvas/pipeline/approve-transition`

GET POST /api/v1/canvas/pipeline/approve-transition

### `GET` `POST /api/v1/canvas/pipeline/run`

Run UnifiedOrchestrator and return summary + context hint

### `GET` `POST /api/v1/canvas/pipeline/{id}/approve-transition`

GET POST /api/v1/canvas/pipeline/{id}/approve-transition

### `GET` `POST /api/v1/canvas/pipeline/{id}/execute`

GET POST /api/v1/canvas/pipeline/{id}/execute

### `GET` `POST /api/v1/canvas/pipeline/{id}/self-improve`

GET POST /api/v1/canvas/pipeline/{id}/self-improve

### `GET` `GET /api/v1/canvas/pipeline/{id}`

GET GET /api/v1/canvas/pipeline/{id}

### `GET` `GET /api/v1/canvas/pipeline/{id}/status`

GET GET /api/v1/canvas/pipeline/{id}/status

### `GET` `GET /api/v1/canvas/pipeline/{id}/stage/{stage}`

GET GET /api/v1/canvas/pipeline/{id}/stage/{stage}

### `GET` `GET /api/v1/canvas/pipeline/{id}/graph`

GET GET /api/v1/canvas/pipeline/{id}/graph

### `GET` `GET /api/v1/canvas/pipeline/{id}/receipt`

GET GET /api/v1/canvas/pipeline/{id}/receipt

### `GET` `GET /api/v1/canvas/pipeline/templates`

GET GET /api/v1/canvas/pipeline/templates

### `GET` `PUT /api/v1/canvas/pipeline/{id}`

GET PUT /api/v1/canvas/pipeline/{id}

### `GET` `POST /api/v1/canvas/pipeline/extract-goals`

GET POST /api/v1/canvas/pipeline/extract-goals

### `GET` `POST /api/v1/canvas/pipeline/extract-principles`

GET POST /api/v1/canvas/pipeline/extract-principles

### `GET` `POST /api/v1/canvas/pipeline/auto-run`

GET POST /api/v1/canvas/pipeline/auto-run

### `GET` `POST /api/v1/canvas/pipeline/from-system-metrics`

GET POST /api/v1/canvas/pipeline/from-system-metrics

### `GET` `POST /api/v1/canvas/convert/debate`

Extract debate_id from a debate result object/dict when available

### `GET` `POST /api/v1/canvas/convert/workflow`

GET POST /api/v1/canvas/convert/workflow

### `GET` `POST /api/v1/debates/{id}/to-pipeline`

GET POST /api/v1/debates/{id}/to-pipeline

### `GET` `GET /api/v1/canvas/pipeline/{id}/intelligence`

GET GET /api/v1/canvas/pipeline/{id}/intelligence

### `GET` `GET /api/v1/canvas/pipeline/{id}/beliefs`

GET GET /api/v1/canvas/pipeline/{id}/beliefs

### `GET` `GET /api/v1/canvas/pipeline/{id}/explanations`

GET GET /api/v1/canvas/pipeline/{id}/explanations

### `GET` `GET /api/v1/canvas/pipeline/{id}/precedents`

GET GET /api/v1/canvas/pipeline/{id}/precedents

### `GET` `GET /api/v1/pipeline/{id}/agents`

GET GET /api/v1/pipeline/{id}/agents

### `GET` `POST /api/v1/pipeline/{id}/agents/{agent_id}/approve`

GET POST /api/v1/pipeline/{id}/agents/{agent_id}/approve

### `GET` `POST /api/v1/pipeline/{id}/agents/{agent_id}/reject`

GET POST /api/v1/pipeline/{id}/agents/{agent_id}/reject

---

## Checkpoints

Checkpoint management endpoint handlers.

### `GET` `/api/checkpoints`

List all checkpoints

### `GET` `/api/checkpoints/{id}`

Get checkpoint details

### `POST` `/api/checkpoints/{id}/resume`

Resume debate from checkpoint

### `DELETE` `/api/checkpoints/{id}`

Delete checkpoint

### `GET` `/api/debates/{id}/checkpoints`

List checkpoints for a debate

### `POST` `/api/debates/{id}/checkpoint`

Create checkpoint for running debate

### `POST` `/api/debates/{id}/pause`

Pause debate and create checkpoint

---

## Cloud Storage

Cloud Storage Handler for Aragora.

### `GET` `/api/v2/storage/files`

List files with filtering

### `POST` `/api/v2/storage/files`

Upload a file

### `GET` `/api/v2/storage/files/:file_id`

Get file metadata

### `GET` `/api/v2/storage/files/:file_id/download`

Download file

### `DELETE` `/api/v2/storage/files/:file_id`

Delete a file

### `POST` `/api/v2/storage/files/:file_id/presign`

Generate presigned URL

### `GET` `/api/v2/storage/quota`

Get storage quota usage

### `GET` `/api/v2/storage/buckets`

List available buckets

### `POST` `/api/v2/storage/buckets`

Create a bucket

### `DELETE` `/api/v2/storage/buckets/:bucket_id`

Delete a bucket

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

## Compliance

HTTP handler for compliance and audit operations.

### `GET` `/api/v1/compliance/rbac-coverage`

GET /api/v1/compliance/rbac-coverage  Returns RBAC endpoint coverage metrics

### `GET` `/api/v2/compliance`

GET /api/v2/compliance

### `GET` `/api/v2/compliance/*`

GET /api/v2/compliance/*

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

## ComputerUse

HTTP request handler for computer use API endpoints.

### `GET` `/api/v1/computer-use/tasks` 🔒

Handle POST /api/v1/computer-use/tasks/{id}/cancel

### `GET` `/api/v1/computer-use/tasks/*`

GET /api/v1/computer-use/tasks/*

### `GET` `/api/v1/computer-use/actions` 🔒

Handle GET /api/v1/computer-use/actions/stats

### `GET` `/api/v1/computer-use/actions/*`

GET /api/v1/computer-use/actions/*

### `GET` `/api/v1/computer-use/actions/stats` 🔒

Handle GET /api/v1/computer-use/actions/stats

### `GET` `/api/v1/computer-use/policies` 🔒

Handle POST /api/v1/computer-use/policies

### `GET` `/api/v1/computer-use/policies/*`

GET /api/v1/computer-use/policies/*

### `GET` `/api/v1/computer-use/approvals` 🔒

Handle POST /api/v1/computer-use/approvals/{id}/approve

### `GET` `/api/v1/computer-use/approvals/*`

GET /api/v1/computer-use/approvals/*

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

### `GET` `/api/consensus/domain/:domain`

Get domain-specific history

---

## Context Budget

Context budget handler for managing debate prompt token budgets.

### `GET` `/api/v1/context/budget`

Get current context budget configuration

### `PUT` `/api/v1/context/budget`

Update context budget settings

### `POST` `/api/v1/context/budget/estimate`

Estimate token usage for given sections

---

## Coordination

Handler for cross-workspace coordination API endpoints.

### `GET` `/api/v1/coordination/workspaces` 🔒

GET /api/v1/coordination/workspaces -- list workspaces

### `GET` `/api/v1/coordination/federation` 🔒

POST /api/v1/coordination/federation -- create federation policy

### `GET` `/api/v1/coordination/execute` 🔒

POST /api/v1/coordination/execute -- cross-workspace execution

### `GET` `/api/v1/coordination/executions` 🔒

GET /api/v1/coordination/executions -- list pending executions

### `GET` `/api/v1/coordination/consent` 🔒

POST /api/v1/coordination/consent -- grant consent

### `GET` `/api/v1/coordination/stats` 🔒

GET /api/v1/coordination/stats -- coordination statistics

### `GET` `/api/v1/coordination/health`

GET /api/v1/coordination/health -- health check

---

## Critique

Critique pattern and reputation endpoint handlers.

### `GET` `/api/critiques/patterns`

Get high-impact critique patterns

### `GET` `/api/critiques/archive`

Get archive statistics

### `GET` `/api/reputation/all`

Get all agent reputations

### `GET` `/api/agent/:name/reputation`

Get specific agent reputation

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

## DAGOperations

HTTP handler for DAG pipeline operations.

### `GET` `POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/debate`

GET POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/debate

### `GET` `POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/decompose`

GET POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/decompose

### `GET` `POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/prioritize`

GET POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/prioritize

### `GET` `POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/assign-agents`

GET POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/assign-agents

### `GET` `POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/execute`

GET POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/execute

### `GET` `POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/find-precedents`

GET POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/find-precedents

### `GET` `POST /api/v1/pipeline/dag/{graph_id}/cluster-ideas`

POST /api/v1/pipeline/dag/{graph_id}/cluster-ideas

### `GET` `POST /api/v1/pipeline/dag/{graph_id}/auto-flow`

POST /api/v1/pipeline/dag/{graph_id}/auto-flow

### `GET` `GET /api/v1/pipeline/dag/{graph_id}`

GET /api/v1/pipeline/dag/{graph_id}

---

## Dashboard

HTTP API Handlers for Dashboard.

### `GET` `/api/v1/dashboard`

Get dashboard overview

### `GET` `/api/v1/dashboard/stats`

Get detailed stats

### `GET` `/api/v1/dashboard/activity`

Get recent activity

### `GET` `/api/v1/dashboard/inbox-summary`

Get inbox summary

### `GET` `/api/v1/dashboard/quick-actions`

Get available quick actions

### `POST` `/api/v1/dashboard/quick-actions/{action}`

Execute quick action

---

## Data Classification Handler

Data Classification Policy HTTP Handler.

### `GET` `/api/v1/data-classification/policy`

Get the active classification policy

### `POST` `/api/v1/data-classification/classify`

Classify data and return metadata

### `POST` `/api/v1/data-classification/validate`

Validate a handling operation

### `POST` `/api/v1/data-classification/enforce`

Enforce cross-context access rules

---

## Debate Intervention

Debate intervention and reasoning endpoint handlers.

### `POST` `/api/v1/debates/{debate_id}/intervene`

Submit a mid-debate intervention

### `GET` `/api/v1/debates/{debate_id}/reasoning`

Get per-agent reasoning summary

---

## Debate Stats

Debate statistics handler for aggregate debate metrics.

### `GET` `/api/v1/debates/stats`

Get aggregate debate statistics

### `GET` `/api/v1/debates/stats/agents`

Get per-agent statistics

---

## Decision

Handler for unified decision-making API endpoints.

### `GET` `/api/v1/decisions`

List recent decisions

### `GET` `/api/v1/decisions/*`

GET /api/v1/decisions/*

---

## DecisionAnalytics

Handler for decision outcome analytics API endpoints.

### `GET` `/api/v1/decision-analytics/overview`

GET /api/v1/decision-analytics/overview

### `GET` `/api/v1/decision-analytics/trends`

GET /api/v1/decision-analytics/trends

### `GET` `/api/v1/decision-analytics/outcomes`

GET /api/v1/decision-analytics/outcomes

### `GET` `/api/v1/decision-analytics/agents`

GET /api/v1/decision-analytics/agents

### `GET` `/api/v1/decision-analytics/domains`

GET /api/v1/decision-analytics/domains

### `GET` `/api/decision-analytics/overview`

GET /api/decision-analytics/overview

### `GET` `/api/decision-analytics/trends`

GET /api/decision-analytics/trends

### `GET` `/api/decision-analytics/outcomes`

GET /api/decision-analytics/outcomes

### `GET` `/api/decision-analytics/agents`

GET /api/decision-analytics/agents

### `GET` `/api/decision-analytics/domains`

GET /api/decision-analytics/domains

---

## Deliberations

Handler for vetted decisionmaking dashboard endpoints.

### `GET` `/api/v1/deliberations/active`

Fetch active vetted decisionmaking sessions from the debate store

### `GET` `/api/v1/deliberations/stats`

Get deliberation statistics

### `GET` `/api/v1/deliberations/stream`

Handle WebSocket stream for real-time updates

### `GET` `/api/v1/deliberations/{deliberation_id}`

GET /api/v1/deliberations/{deliberation_id}

---

## Dependency Analysis

HTTP API Handlers for Dependency Analysis.

### `POST` `/api/v1/codebase/analyze-dependencies`

Analyze project dependencies

### `GET` `/api/v1/codebase/sbom`

Generate SBOM

### `POST` `/api/v1/codebase/scan-vulnerabilities`

Scan for CVEs

### `POST` `/api/v1/codebase/check-licenses`

Check license compatibility

---

## Devices

Device Registration and Notification API Handlers.

### `POST` `/api/devices/register`

Register a device for push notifications

### `DELETE` `/api/devices/{device_id}`

Unregister a device

### `POST` `/api/devices/{device_id}/notify`

Send notification to a device

### `POST` `/api/devices/user/{user_id}/notify`

Send to all user devices

### `GET` `/api/devices/user/{user_id}`

List user's devices

### `GET` `/api/devices/health`

Get device connector health

### `POST` `/api/devices/alexa/webhook`

Alexa skill webhook

### `POST` `/api/devices/google/webhook`

Google Actions webhook

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

## Dr Handler

Disaster Recovery HTTP Handlers for Aragora.

### `GET` `/api/v2/dr/status`

Get DR readiness status

### `POST` `/api/v2/dr/drill`

Run DR drill (simulated recovery)

### `GET` `/api/v2/dr/objectives`

Get RPO/RTO objectives and current status

### `POST` `/api/v2/dr/validate`

Validate DR configuration

---

## EmailDebate

Handler for email vetted decisionmaking API endpoints.

### `GET` `/api/v1/email/prioritize`

Prioritize multiple emails

### `GET` `/api/v1/email/prioritize/batch`

Prioritize multiple emails

### `GET` `/api/v1/email/triage`

Full inbox triage with categorization and sorting

---

## Email Services

HTTP API Handlers for Email Services.

### `POST` `/api/v1/email/followups/mark`

Mark email as awaiting reply

### `GET` `/api/v1/email/followups/pending`

List pending follow-ups

### `POST` `/api/v1/email/followups/{id}/resolve`

Resolve a follow-up

### `POST` `/api/v1/email/followups/check-replies`

Check for replies

### `GET` `/api/v1/email/{id}/snooze-suggestions`

Get snooze recommendations

### `POST` `/api/v1/email/{id}/snooze`

Apply snooze to email

### `DELETE` `/api/v1/email/{id}/snooze`

Cancel snooze

### `GET` `/api/v1/email/snoozed`

List snoozed emails

### `GET` `/api/v1/email/categories`

List available categories

### `POST` `/api/v1/email/categories/learn`

Submit category feedback

---

## EmailTriage

Handler for email triage rules management.

### `GET` `/api/v1/email/triage/rules`

Return current triage rules

### `GET` `/api/v1/email/triage/test`

Test a message against current triage rules

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

## ERC8004

Handler for ERC-8004 blockchain API endpoints.

### `GET` `/api/v1/blockchain/config`

GET /api/v1/blockchain/config

### `GET` `/api/v1/blockchain/health`

GET /api/v1/blockchain/health

### `GET` `/api/v1/blockchain/sync`

GET /api/v1/blockchain/sync

### `GET` `/api/v1/blockchain/agents`

GET /api/v1/blockchain/agents

### `GET` `/api/v1/blockchain/agents/*`

GET /api/v1/blockchain/agents/*

---

## Evaluation

Handler for LLM-as-Judge evaluation endpoints.

### `GET` `/api/v1/evaluate` 🔒

Evaluate a response using LLM-as-Judge

### `GET` `/api/v1/evaluate/compare` 🔒

Compare two responses using pairwise evaluation

### `GET` `/api/v1/evaluate/dimensions` 🔒

List available evaluation dimensions

### `GET` `/api/v1/evaluate/profiles` 🔒

List available evaluation weight profiles

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

## Explainability

Handler for debate explainability endpoints.

### `GET` `/api/v1/debates/*/explanation`

Build explanation dictionary based on options

### `GET` `/api/v1/debates/*/evidence`

Handle evidence chain request

### `GET` `/api/v1/debates/*/votes/pivots`

Handle vote pivot analysis request

### `GET` `/api/v1/debates/*/counterfactuals`

Handle counterfactual analysis request

### `GET` `/api/v1/explain`

GET /api/v1/explain

### `GET` `/api/v1/explain/*`

GET /api/v1/explain/*

### `GET` `/api/v1/explainability/batch` 🔒

Create a new batch explainability job

### `GET` `/api/v1/explainability/batch/*/status`

Get status of a batch job

### `GET` `/api/v1/explainability/batch/*/results`

Get results of a completed batch job

### `GET` `/api/v1/explainability/compare` 🔒

Compare explanations between multiple debates

### `GET` `/api/v1/debates/*/explanation`

Build explanation dictionary based on options

### `GET` `/api/v1/explain/*`

GET /api/v1/explain/*

---

## External Agents

External Agent Gateway endpoint handlers.

### `POST` `/api/external-agents/tasks`

Submit task to external agent

### `GET` `/api/external-agents/tasks/{id}`

Get task status/result

### `DELETE` `/api/external-agents/tasks/{id}`

Cancel task

### `GET` `/api/external-agents/adapters`

List registered adapters

### `GET` `/api/external-agents/health`

Health check all adapters

---

## External Integrations

External Integrations API Handler.

### `POST` `/api/integrations/zapier/apps`

Create Zapier app

### `GET` `/api/integrations/zapier/apps`

List Zapier apps

### `DELETE` `/api/integrations/zapier/apps/:id`

Delete Zapier app

### `POST` `/api/integrations/zapier/triggers`

Subscribe to trigger

### `DELETE` `/api/integrations/zapier/triggers/:id`

Unsubscribe trigger

### `GET` `/api/integrations/zapier/triggers`

List trigger types

### `POST` `/api/integrations/make/connections`

Create Make connection

### `GET` `/api/integrations/make/connections`

List Make connections

### `DELETE` `/api/integrations/make/connections/:id`

Delete Make connection

### `POST` `/api/integrations/make/webhooks`

Register webhook

### `DELETE` `/api/integrations/make/webhooks/:id`

Unregister webhook

### `GET` `/api/integrations/make/modules`

List available modules

### `POST` `/api/integrations/n8n/credentials`

Create n8n credential

### `GET` `/api/integrations/n8n/credentials`

List n8n credentials

### `DELETE` `/api/integrations/n8n/credentials/:id`

Delete n8n credential

### `POST` `/api/integrations/n8n/webhooks`

Register webhook

### `DELETE` `/api/integrations/n8n/webhooks/:id`

Unregister webhook

### `GET` `/api/integrations/n8n/nodes`

Get node definitions

---

## Feature Flags

Feature flags handler for reading flag values.

### `GET` `/api/v1/feature-flags`

List all feature flags with current values

### `GET` `/api/v1/feature-flags/:name`

Get a specific flag value

---

## Feedback

User Feedback Collection Handler.

### `POST` `/api/v1/feedback/nps`

Submit NPS score (requires feedback.write)

### `POST` `/api/v1/feedback/general`

Submit general feedback (requires feedback.write)

### `GET` `/api/v1/feedback/nps/summary`

Get NPS summary (requires feedback.update - admin)

### `GET` `/api/v1/feedback/prompts`

Get active feedback prompts (requires feedback.read)

---

## Feedback Hub

Feedback Hub endpoint handlers.

### `GET` `/api/v1/feedback-hub/stats`

Routing statistics

### `GET` `/api/v1/feedback-hub/history`

Recent routing history

---

## Gallery

Public Gallery endpoint handlers.

### `GET` `/api/gallery`

List public debates

### `GET` `/api/gallery/:debate_id`

Get specific debate with full history

### `GET` `/api/gallery/:debate_id/embed`

Get embeddable debate summary

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

## GatewayAgents

HTTP request handler for external agent registration endpoints.

### `GET` `/api/v1/gateway/agents`

Extract agent name from path like /api/v1/gateway/agents/{name}

### `GET` `/api/v1/gateway/agents/*`

GET /api/v1/gateway/agents/*

---

## GatewayConfig

HTTP handler for gateway configuration endpoints.

### `GET` `/api/v1/gateway/config` 🔒

Handle GET /api/v1/gateway/config

### `GET` `/api/v1/gateway/config/defaults` 🔒

Handle GET /api/v1/gateway/config/defaults

---

## GatewayCredentials

HTTP request handler for gateway credential management endpoints.

### `GET` `/api/v1/gateway/credentials`

Extract credential ID from path like /api/v1/gateway/credentials/{id}

### `GET` `/api/v1/gateway/credentials/*`

GET /api/v1/gateway/credentials/*

---

## Gateway

HTTP request handler for gateway API endpoints.

### `GET` `/api/v1/gateway/devices` 🔒

Handle GET /api/v1/gateway/devices/{id}

### `GET` `/api/v1/gateway/devices/*`

GET /api/v1/gateway/devices/*

### `GET` `/api/v1/gateway/channels` 🔒

Handle GET /api/v1/gateway/channels

### `GET` `/api/v1/gateway/routing` 🔒

Handle GET /api/v1/gateway/routing/rules

### `GET` `/api/v1/gateway/routing/*`

GET /api/v1/gateway/routing/*

### `GET` `/api/v1/gateway/routing/rules` 🔒

Handle GET /api/v1/gateway/routing/rules

### `GET` `/api/v1/gateway/routing/stats` 🔒

Handle GET /api/v1/gateway/routing/stats

### `GET` `/api/v1/gateway/messages` 🔒

Handle POST /api/v1/gateway/messages/route

### `GET` `/api/v1/gateway/messages/*`

GET /api/v1/gateway/messages/*

### `GET` `/api/v1/gateway/messages/route`

Get or create agent router

---

## GatewayHealth

HTTP handler for gateway health endpoints.

### `GET` `/api/v1/gateway/health` 🔒

Handle GET /api/v1/gateway/agents/{name}/health

### `GET` `/api/v1/gateway/agents/*/health` 🔒

Handle GET /api/v1/gateway/agents/{name}/health

---

## Gdpr Deletion

GDPR Self-Service Deletion Handler.

### `POST` `/api/v1/users/self/deletion`

request  (schedule with grace period)

### `GET` `/api/v1/users/self/deletion`

request   (check status)

### `DELETE` `/api/v1/users/self/deletion`

request   (cancel during grace period)

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

### `GET` `/api/genesis/genomes/:genome_id`

Get single genome details

---

## Harnesses

External harness endpoint handlers.

### `GET` `/api/v1/harnesses`

List available harnesses

### `GET` `/api/v1/harnesses/{name}/status`

Get harness status

### `POST` `/api/v1/harnesses/{name}/execute`

Execute a command via harness

---

## HybridDebate

HTTP request handler for hybrid debate API endpoints.

### `GET` `/api/v1/debates/hybrid` 🔒

Handle POST /api/v1/debates/hybrid

### `GET` `/api/v1/debates/hybrid/*`

GET /api/v1/debates/hybrid/*

---

## IdeaCanvas

Handler for Idea Canvas REST API endpoints.

### `GET` `/api/v1/ideas`

GET /api/v1/ideas

### `GET` `/api/v1/ideas/*`

GET /api/v1/ideas/*

### `GET` `/api/v1/ideas/*/nodes` 🔒

GET /api/v1/ideas/*/nodes

### `GET` `/api/v1/ideas/*/nodes/*`

GET /api/v1/ideas/*/nodes/*

### `GET` `/api/v1/ideas/*/edges`

GET /api/v1/ideas/*/edges

### `GET` `/api/v1/ideas/*/edges/*`

GET /api/v1/ideas/*/edges/*

### `GET` `/api/v1/ideas/*/export` 🔒

GET /api/v1/ideas/*/export

### `GET` `/api/v1/ideas/*/promote` 🔒

GET /api/v1/ideas/*/promote

---

## Inbox Command

Inbox Command Center API Handler.

### `GET` `/api/inbox/command`

Fetch prioritized inbox

### `POST` `/api/inbox/actions`

Execute quick action

### `POST` `/api/inbox/bulk-actions`

Execute bulk action

### `GET` `/api/inbox/sender-profile`

Get sender profile

### `GET` `/api/inbox/daily-digest`

Get daily digest

### `POST` `/api/inbox/reprioritize`

Trigger AI re-prioritization

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

### `PUT` `/api/v1/accounting/invoices/{id}`

Update invoice

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

## KnowledgeChat

HTTP handler for Knowledge + Chat bridge endpoints.

### `GET` `/api/v1/chat/knowledge/search`

GET /api/v1/chat/knowledge/search

### `GET` `/api/v1/chat/knowledge/inject`

GET /api/v1/chat/knowledge/inject

### `GET` `/api/v1/chat/knowledge/store`

GET /api/v1/chat/knowledge/store

### `GET` `/api/v1/chat/knowledge/channel/*`

GET /api/v1/chat/knowledge/channel/*

### `GET` `/api/v1/chat/knowledge/channel/*/summary`

GET /api/v1/chat/knowledge/channel/*/summary

---

## Knowledge Flow

Knowledge Flow HTTP Handler — Debate -> KM -> Debate flywheel visualization.

### `GET` `/api/knowledge/flow`

Flow data (debate->KM->debate)

### `GET` `/api/knowledge/flow/confidence-history`

Confidence changes over time

### `GET` `/api/knowledge/adapters/health`

All adapter statuses

---

## Laboratory

Persona laboratory endpoint handlers.

### `GET` `/api/laboratory/emergent-traits`

Get emergent traits from agent performance

### `GET` `/api/laboratory/agent/{agent_name}/analysis`

Get trait analysis for an agent

### `POST` `/api/laboratory/cross-pollinations/suggest`

Suggest beneficial trait transfers

---

## Marketplace

Marketplace API Handlers.

### `GET` `/api/v1/marketplace/templates`

List all templates

### `GET` `/api/v1/marketplace/templates/{id}`

Get template details

### `POST` `/api/v1/marketplace/templates`

Create a template

### `DELETE` `/api/v1/marketplace/templates/{id}`

Delete a template

### `POST` `/api/v1/marketplace/templates/{id}/ratings`

Rate a template

### `GET` `/api/v1/marketplace/templates/{id}/ratings`

Get template ratings

### `POST` `/api/v1/marketplace/templates/{id}/star`

Star a template

### `GET` `/api/v1/marketplace/categories`

List categories

### `GET` `/api/v1/marketplace/templates/{id}/export`

Export template

### `POST` `/api/v1/marketplace/templates/import`

Import a template

### `GET` `/api/v1/marketplace/status`

Health and circuit breaker status

---

## MarketplaceBrowse

Handler for marketplace template browsing endpoints.

### `GET` `/api/v1/marketplace/templates`

GET /api/v1/marketplace/templates

### `GET` `/api/v1/marketplace/templates/*`

GET /api/v1/marketplace/templates/*

### `GET` `/api/v1/marketplace/featured`

Return featured templates

### `GET` `/api/v1/marketplace/popular`

Return popular templates sorted by downloads

---

## Marketplace Pilot

Marketplace Pilot API Handler.

### `GET` `/api/v1/marketplace/listings`

Browse listings with filters

### `GET` `/api/v1/marketplace/listings/featured`

Featured listings

### `GET` `/api/v1/marketplace/listings/stats`

Marketplace statistics

### `GET` `/api/v1/marketplace/listings/{id}`

Get listing details

### `POST` `/api/v1/marketplace/listings/{id}/install`

Install a listing

### `POST` `/api/v1/marketplace/listings/{id}/rate`

Rate a listing

### `POST` `/api/v1/marketplace/listings/{id}/launch-debate`

Launch debate from listing

---

## MCPTools

Handler for MCP tool discovery endpoints.

### `GET` `GET /api/v1/mcp/tools`

Return the full MCP tool catalog

### `GET` `GET /api/v1/mcp/tools/{name}`

GET GET /api/v1/mcp/tools/{name}

---

## Memory Unified

Unified Memory Gateway HTTP Handler (DEPRECATED).

### `POST` `/api/memory/unified/query`

Fan-out search across all systems

### `GET` `/api/memory/unified/retention`

RetentionGate decisions

### `GET` `/api/memory/unified/dedup`

Near-duplicate clusters

### `GET` `/api/memory/unified/sources`

Memory source breakdown

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

## Ml

ML (Machine Learning) endpoint handlers.

### `POST` `/api/ml/route`

Get ML-based agent routing for a task

### `POST` `/api/ml/score`

Score response quality

### `POST` `/api/ml/score-batch`

Score multiple responses

### `POST` `/api/ml/consensus`

Predict consensus likelihood

### `POST` `/api/ml/export-training`

Export debate data for training

### `GET` `/api/ml/models`

List available ML models/capabilities

### `GET` `/api/ml/stats`

Get ML module statistics

---

## Moderation

Handler for moderation configuration and review queue.

### `GET` `/api/moderation/config` 🔒

GET /api/moderation/config

### `GET` `/api/moderation/stats` 🔒

GET /api/moderation/stats

### `GET` `/api/moderation/queue` 🔒

GET /api/moderation/queue

### `GET` `/api/moderation/items/*/approve`

GET /api/moderation/items/*/approve

### `GET` `/api/moderation/items/*/reject`

GET /api/moderation/items/*/reject

---

## ModerationAnalytics

Handler for moderation analytics dashboard endpoints.

### `GET` `/api/v1/moderation/stats`

Return moderation statistics

### `GET` `/api/v1/moderation/queue`

Return pending review items

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

## Nomic

Nomic loop state and monitoring endpoint handlers.

### `GET` `/api/nomic/state`

Get nomic loop state

### `GET` `/api/nomic/health`

Get nomic loop health with stall detection

### `GET` `/api/nomic/metrics`

Get nomic loop Prometheus metrics summary

### `GET` `/api/nomic/log`

Get nomic loop logs

### `GET` `/api/nomic/risk-register`

Get risk register entries

### `GET` `/api/nomic/witness/status`

Get Gas Town witness patrol status

### `GET` `/api/nomic/mayor/current`

Get current Gas Town mayor information

### `GET` `/api/modes`

Get available operational modes

### `WS` `/api/nomic/stream`

Real-time WebSocket event stream

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

## OpenClawGateway

HTTP handler for OpenClaw gateway operations.

### `GET` `/api/v1/openclaw/sessions` 🔒

List sessions with optional filtering

### `GET` `/api/v1/openclaw/sessions/{session_id}`

GET /api/v1/openclaw/sessions/{session_id}

### `GET` `/api/v1/openclaw/sessions/{session_id}/end` 🔒

End a session via POST (SDK-compatible endpoint)

### `GET` `/api/v1/openclaw/actions`

GET /api/v1/openclaw/actions

### `GET` `/api/v1/openclaw/actions/{action_id}`

GET /api/v1/openclaw/actions/{action_id}

### `GET` `/api/v1/openclaw/actions/{action_id}/cancel` 🔒

Cancel a running action

### `GET` `/api/v1/openclaw/credentials` 🔒

List credentials (metadata only, no secret values)

### `GET` `/api/v1/openclaw/credentials/{credential_id}`

GET /api/v1/openclaw/credentials/{credential_id}

### `GET` `/api/v1/openclaw/credentials/{credential_id}/rotate` 🔒

Rotate a credential's secret value

### `GET` `/api/v1/openclaw/policy/rules` 🔒

Get active policy rules

### `GET` `/api/v1/openclaw/policy/rules/{rule_name}`

GET /api/v1/openclaw/policy/rules/{rule_name}

### `GET` `/api/v1/openclaw/approvals` 🔒

List pending approval requests

### `GET` `/api/v1/openclaw/approvals/{approval_id}/approve` 🔒

Approve a pending action

### `GET` `/api/v1/openclaw/approvals/{approval_id}/deny` 🔒

Deny a pending action

### `GET` `/api/v1/openclaw/health`

Get gateway health status

### `GET` `/api/v1/openclaw/metrics` 🔒

Get gateway metrics

### `GET` `/api/v1/openclaw/audit` 🔒

Get audit log entries

### `GET` `/api/v1/openclaw/stats` 🔒

Get proxy statistics

### `GET` `/api/gateway/openclaw/sessions` 🔒

List sessions with optional filtering

### `GET` `/api/gateway/openclaw/actions`

GET /api/gateway/openclaw/actions

### `GET` `/api/gateway/openclaw/credentials` 🔒

List credentials (metadata only, no secret values)

### `GET` `/api/gateway/openclaw/health`

Get gateway health status

### `GET` `/api/gateway/openclaw/metrics` 🔒

Get gateway metrics

### `GET` `/api/gateway/openclaw/audit` 🔒

Get audit log entries

---

## OperatorIntervention

Handler for operator intervention control endpoints.

### `GET` `/api/v1/interventions/active`

List all active intervention-tracked debates

---

## Organizations

Organization Management Handlers.

### `GET` `/api/org/{org_id}`

Get organization details

### `PUT` `/api/org/{org_id}`

Update organization settings

### `GET` `/api/org/{org_id}/members`

List organization members

### `POST` `/api/org/{org_id}/invite`

Invite user to organization

### `GET` `/api/org/{org_id}/invitations`

List pending invitations

### `DELETE` `/api/org/{org_id}/invitations/{invitation_id}`

Revoke invitation

### `DELETE` `/api/org/{org_id}/members/{user_id}`

Remove member

### `PUT` `/api/org/{org_id}/members/{user_id}/role`

Update member role

### `GET` `/api/invitations/pending`

List pending invitations for current user

### `POST` `/api/invitations/{token}/accept`

Accept an invitation

### `GET` `/api/user/organizations`

List organizations for current user

### `POST` `/api/user/organizations/switch`

Switch active organization

### `POST` `/api/user/organizations/default`

Set default organization

### `DELETE` `/api/user/organizations/{org_id}`

Leave organization

---

## OutcomeAnalytics

Handler for decision outcome analytics endpoints.

### `GET` `/api/analytics/outcomes` 🔒

GET /api/analytics/outcomes/average-rounds

### `GET` `/api/analytics/outcomes/consensus-rate` 🔒

GET /api/analytics/outcomes/consensus-rate

### `GET` `/api/analytics/outcomes/average-rounds` 🔒

GET /api/analytics/outcomes/average-rounds

### `GET` `/api/analytics/outcomes/contributions` 🔒

GET /api/analytics/outcomes/contributions

### `GET` `/api/analytics/outcomes/quality-trend` 🔒

GET /api/analytics/outcomes/quality-trend

### `GET` `/api/analytics/outcomes/topics` 🔒

GET /api/analytics/outcomes/topics

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

## Partner

Partner API HTTP handlers.

### `POST` `/api/partners/register`

Register as a partner

### `GET` `/api/partners/me`

Get current partner profile

### `POST` `/api/partners/keys`

Create API key

### `GET` `/api/partners/keys`

List API keys

### `POST` `/api/partners/keys/{key_id}/rotate`

Rotate API key

### `DELETE` `/api/partners/keys/{key_id}`

Revoke API key

### `GET` `/api/partners/usage`

Get usage statistics

### `POST` `/api/partners/webhooks`

Configure webhook

### `GET` `/api/partners/limits`

Get rate limits

---

## Persona

Persona-related endpoint handlers.

### `GET` `/api/personas`

Get all agent personas

### `GET` `/api/agent/{name}/persona`

Get agent persona

### `GET` `/api/agent/{name}/grounded-persona`

Get truth-grounded persona

### `GET` `/api/agent/{name}/identity-prompt`

Get identity prompt

### `GET` `/api/agent/{name}/performance`

Get agent performance summary

### `GET` `/api/agent/{name}/domains`

Get agent expertise domains

### `GET` `/api/agent/{name}/accuracy`

Get position accuracy stats

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

## Pipeline Telemetry

Pipeline Telemetry REST Handler.

### `GET` `/api/v1/pipeline/telemetry`

Stage timing metrics

---

## Plans

Decision Plan API handler.

### `POST` `/api/v1/plans`

Create plan from debate result

### `GET` `/api/v1/plans`

List plans with pagination

### `GET` `/api/v1/plans/{id}`

Get plan details

### `POST` `/api/v1/plans/{id}/approve`

Approve a plan

### `POST` `/api/v1/plans/{id}/reject`

Reject a plan with reason

### `POST` `/api/v1/plans/{id}/execute`

Execute an approved plan

---

## Platform Config

Platform Configuration handler.

### `GET` `/api/v1/platform/config`

Full platform configuration

---

## Playbook

Handler for playbook API endpoints.

### `GET` `/api/playbooks`

Extract playbook ID from a path like /api/playbooks/{id}[/run]

---

## Playground

HTTP handler for the public playground demo.

### `GET` `/api/v1/playground/assess`

Assess question ambiguity using a frontier model

### `GET` `/api/v1/playground/debate`

Retrieve a saved debate by ID for shareable links

### `GET` `/api/v1/playground/assess`

Assess question ambiguity using a frontier model

### `GET` `/api/v1/playground/debate/live`

Run a live debate with real API-backed agents

### `GET` `/api/v1/playground/debate/live/cost-estimate`

GET /api/v1/playground/debate/live/cost-estimate

### `GET` `/api/v1/playground/landing/events`

GET /api/v1/playground/landing/events

### `GET` `/api/v1/playground/landing/events/summary`

Summarize recent landing telemetry without exposing raw events

### `GET` `/api/v1/playground/landing/feedback`

Accept a bounded wrong-answer report from the landing page

### `GET` `/api/v1/playground/landing/feedback/review`

Update admin review state for a wrong-answer report

### `GET` `/api/v1/playground/status`

GET /api/v1/playground/status

### `GET` `/api/v1/playground/tts` 🔒

Proxy text-to-speech through ElevenLabs, returning audio/mpeg

---

## Policy

Policy and Compliance endpoint handlers.

### `GET` `/api/policies`

List policies

### `GET` `/api/policies/:id`

Get policy details

### `POST` `/api/policies`

Create policy

### `PATCH` `/api/policies/:id`

Update policy

### `DELETE` `/api/policies/:id`

Delete policy

### `POST` `/api/policies/:id/toggle`

Toggle policy enabled status

### `GET` `/api/policies/:id/violations`

Get violations for a policy

### `GET` `/api/compliance/violations`

List all violations

### `GET` `/api/compliance/violations/:id`

Get violation details

### `PATCH` `/api/compliance/violations/:id`

Update violation status

### `POST` `/api/compliance/check`

Run compliance check on content

### `GET` `/api/compliance/stats`

Get compliance statistics

---

## Privacy

Privacy Handler - GDPR/CCPA Compliant Data Export and Account Deletion.

### `GET` `/api/privacy/export`

Export all user data (GDPR Article 15, CCPA Right to Know)

### `GET` `/api/privacy/data-inventory`

Get summary of data categories collected

### `DELETE` `/api/privacy/account`

Delete user account (GDPR Article 17, CCPA Right to Delete)

### `POST` `/api/privacy/preferences`

Update privacy preferences (CCPA Do Not Sell)

---

## Queue

Queue management endpoint handlers.

### `POST` `/api/queue/jobs`

Submit new job

### `GET` `/api/queue/jobs`

List jobs with filters

### `GET` `/api/queue/jobs/:id`

Get job status

### `POST` `/api/queue/jobs/:id/retry`

Retry failed job

### `DELETE` `/api/queue/jobs/:id`

Cancel job

### `GET` `/api/queue/stats`

Queue statistics

### `GET` `/api/queue/workers`

Worker status

---

## RalphDashboard

Handler for Ralph campaign dashboard endpoints.

### `GET` `/api/ralph/campaigns` 🔒

GET /api/ralph/campaigns

### `GET` `/api/ralph/campaigns/{campaign_id}`

GET /api/ralph/campaigns/{campaign_id}

### `GET` `/api/ralph/campaigns/{campaign_id}/timeline` 🔒

GET /api/ralph/campaigns/{campaign_id}/timeline

### `GET` `/api/ralph/campaigns/{campaign_id}/blockers` 🔒

GET /api/ralph/campaigns/{campaign_id}/blockers

### `GET` `/api/ralph/campaigns/{campaign_id}/repairs` 🔒

GET /api/ralph/campaigns/{campaign_id}/repairs

### `GET` `/api/ralph/campaigns/{campaign_id}/budget` 🔒

GET /api/ralph/campaigns/{campaign_id}/budget

### `GET` `/api/ralph/campaigns/{campaign_id}/pr-gate`

GET /api/ralph/campaigns/{campaign_id}/pr-gate

### `GET` `/api/ralph/overview` 🔒

GET /api/ralph/overview

### `GET` `/api/ralph/blockers` 🔒

GET /api/ralph/blockers

---

## RBAC

HTTP handler for RBAC management endpoints.

### `GET` `/api/v1/rbac/permissions` 🔒

List all system permissions with optional filtering

### `GET` `/api/v1/rbac/permissions/*`

GET /api/v1/rbac/permissions/*

### `GET` `/api/v1/rbac/roles` 🔒

List all roles (system and custom)

### `GET` `/api/v1/rbac/roles/*`

GET /api/v1/rbac/roles/*

### `GET` `/api/v1/rbac/assignments` 🔒

List role assignments with optional filtering

### `GET` `/api/v1/rbac/assignments/*`

GET /api/v1/rbac/assignments/*

### `GET` `/api/v1/rbac/check` 🔒

Check if a user has a specific permission

---

## ReadinessCheck

Public endpoint reporting what a user needs to configure before

### `GET` `/api/v1/readiness`

GET /api/v1/readiness

### `GET` `/api/readiness`

GET /api/readiness

---

## Receipts

Decision Receipt HTTP Handlers for Aragora.

### `GET` `/api/v2/receipts`

List receipts with filters

### `GET` `/api/v2/receipts/search`

Full-text search receipts

### `GET` `/api/v2/receipts/:receipt_id`

Get specific receipt

### `GET` `/api/v2/receipts/:receipt_id/export`

Export (format=json|html|md|pdf)

### `GET` `/api/v2/receipts/:receipt_id/verify`

Verify integrity + signature

### `POST` `/api/v2/receipts/:receipt_id/verify`

Verify integrity checksum

### `POST` `/api/v2/receipts/:receipt_id/verify-signature`

Verify cryptographic signature

### `POST` `/api/v2/receipts/verify-batch`

Batch signature verification

### `POST` `/api/v2/receipts/sign-batch`

Batch signing

### `POST` `/api/v2/receipts/batch-export`

Batch export to ZIP

### `GET` `/api/v2/receipts/stats`

Receipt statistics

### `POST` `/api/v2/receipts/:receipt_id/share`

Create shareable link

### `GET` `/api/v2/receipts/share/:token`

Access receipt via share token

### `GET` `/api/v2/receipts/signing-key`

ODR signing public key (JSON envelope)

### `GET` `/.well-known/aragora-odr-signing-key`

ODR signing public key (raw PEM)

### `GET` `/api/v1/receipts/deliveries`

Legacy/frontend delivery history bridge

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

## Repository

Repository indexing endpoint handlers.

### `POST` `/api/repository/index`

Start full repository index

### `POST` `/api/repository/incremental`

Incremental update

### `GET` `/api/repository/:id/status`

Get indexing status

### `GET` `/api/repository/:id/entities`

List entities with filters

### `GET` `/api/repository/:id/graph`

Get relationship graph

### `DELETE` `/api/repository/:id`

Remove indexed repository

---

## ReviewQueue

HTTP handler for PDB UI v0 review-queue endpoints.

### `GET` `/api/review-queue/*`

GET /api/review-queue/*

### `GET` `/api/v1/review-queue/*`

GET /api/v1/review-queue/*

---

## Reviews

Reviews Handler - Serve shareable code reviews.

### `GET` `/api/reviews/{id}`

Get a specific review by ID

### `GET` `/api/reviews`

List recent reviews

---

## RLMContext

Handler for RLM context compression and query endpoints.

### `GET` `/api/v1/rlm/stats`

GET /api/v1/rlm/stats

### `GET` `/api/v1/rlm/strategies`

GET /api/v1/rlm/strategies

### `GET` `/api/v1/rlm/compress`

Get or create the hierarchical compressor using factory

### `GET` `/api/v1/rlm/query`

Simple fallback query when full RLM is not available

### `GET` `/api/v1/rlm/contexts`

GET /api/v1/rlm/contexts

### `GET` `/api/v1/rlm/stream`

GET /api/v1/rlm/stream

### `GET` `/api/v1/rlm/stream/modes`

GET /api/v1/rlm/stream/modes

### `GET` `/api/v1/rlm/codebase/health`

GET /api/v1/rlm/codebase/health

---

## Runs

Backbone run ledger handlers.

### `GET` `/api/runs`

List persisted backbone runs

### `GET` `/api/runs/{run_id}`

Fetch one persisted backbone run

---

## Sandbox

Sandbox execution endpoint handlers.

### `POST` `/api/sandbox/execute`

Execute code in sandbox

### `DELETE` `/api/sandbox/executions/{id}`

Cancel a running execution

### `GET` `/api/sandbox/config`

Get sandbox configuration

### `PUT` `/api/sandbox/config`

Update sandbox configuration

### `GET` `/api/sandbox/pool/status`

Get container pool status

---

## SCIM

HTTP request handler for SCIM 2.0 provisioning endpoints.

### `GET` `/scim/v2/Users`

Extract resource ID from path like /scim/v2/Users/{id}

### `GET` `/scim/v2/Users/*`

GET /scim/v2/Users/*

### `GET` `/scim/v2/Groups`

GET /scim/v2/Groups

### `GET` `/scim/v2/Groups/*`

GET /scim/v2/Groups/*

---

## Security Debate

Security Debate API endpoint handlers.

### `POST` `/api/v1/audit/security/debate`

Trigger a security debate on findings

### `GET` `/api/v1/audit/security/debate/:id`

Get status of a security debate

---

## Selection

Handler for selection plugin endpoints.

### `GET` `/api/v1/selection/plugins` 🔒

List all available selection plugins

### `GET` `/api/v1/selection/defaults` 🔒

Get default plugin configuration

### `GET` `/api/v1/selection/scorers` 🔒

List available scorer plugins

### `GET` `/api/v1/selection/team-selectors`

GET /api/v1/selection/team-selectors

### `GET` `/api/v1/selection/role-assigners`

GET /api/v1/selection/role-assigners

### `GET` `/api/v1/selection/score` 🔒

Get information about a specific scorer

### `GET` `/api/v1/selection/team` 🔒

Get information about a specific team selector

### `GET` `/api/v1/team-selection`

GET /api/v1/team-selection

### `GET` `/api/v1/agent-selection/plugins` 🔒

List all available selection plugins

### `GET` `/api/v1/agent-selection/defaults` 🔒

Get default plugin configuration

### `GET` `/api/v1/agent-selection/score` 🔒

Get information about a specific scorer

### `GET` `/api/v1/agent-selection/best`

GET /api/v1/agent-selection/best

### `GET` `/api/v1/agent-selection/select-team`

GET /api/v1/agent-selection/select-team

### `GET` `/api/v1/agent-selection/assign-roles`

GET /api/v1/agent-selection/assign-roles

### `GET` `/api/v1/agent-selection/history` 🔒

Get agent selection history

---

## Self Improve

Self-improvement run management endpoints.

### `POST` `/api/self-improve/run`

Start a new self-improvement cycle

### `POST` `/api/self-improve/start`

Start a new run (legacy alias)

### `GET` `/api/self-improve/status`

Get current cycle status (running/idle)

### `GET` `/api/self-improve/runs`

List all runs

### `GET` `/api/self-improve/runs/:id`

Get run status and progress

### `GET` `/api/self-improve/history`

Get run history (alias for /runs)

### `GET` `/api/self-improve/feedback`

Get feedback loop state and metrics

### `POST` `/api/self-improve/runs/:id/cancel`

Cancel a running run

### `POST` `/api/self-improve/coordinate`

Start a hierarchical coordination cycle

### `GET` `/api/self-improve/worktrees`

List active worktrees

### `POST` `/api/self-improve/worktrees/cleanup`

Clean up all worktrees

### `GET` `/api/self-improve/worktrees/autopilot/status`

Managed autopilot session status

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

### `GET` `/api/self-improve/meta-planner/goals`

MetaPlanner prioritized goals

### `GET` `/api/self-improve/execution/timeline`

Branch execution timeline

### `GET` `/api/self-improve/learning/insights`

Cross-cycle learning data

### `GET` `/api/self-improve/metrics/comparison`

Before/after codebase metrics

### `POST` `/api/self-improve/improvement-queue`

User-submitted improvement goals

### `PUT` `/api/self-improve/improvement-queue/{id}/priority`

Reorder queue items

### `DELETE` `/api/self-improve/improvement-queue/{id}`

Remove queue items

---

## Settlement

Handler for settlement API endpoints.

### `GET` `/api/settlements`

GET /api/settlements

### `GET` `/api/settlements/history` 🔒

Get settled (resolved) settlements

### `GET` `/api/settlements/summary` 🔒

Get overall settlement summary statistics

### `GET` `/api/settlements/{id}`

GET /api/settlements/{id}

### `GET` `/api/settlements/{id}/settle` 🔒

Get a specific settlement by ID

### `GET` `/api/settlements/batch` 🔒

Settle multiple claims at once

### `GET` `/api/settlements/agent/{agent}/accuracy` 🔒

Get accuracy statistics for a specific agent

### `GET` `/api/v1/settlements`

GET /api/v1/settlements

### `GET` `/api/v1/settlements/history` 🔒

Get settled (resolved) settlements

### `GET` `/api/v1/settlements/summary` 🔒

Get overall settlement summary statistics

### `GET` `/api/v1/settlements/{id}`

GET /api/v1/settlements/{id}

### `GET` `/api/v1/settlements/{id}/settle` 🔒

Get a specific settlement by ID

### `GET` `/api/v1/settlements/batch` 🔒

Settle multiple claims at once

### `GET` `/api/v1/settlements/agent/{agent}/accuracy` 🔒

Get accuracy statistics for a specific agent

---

## Skill Marketplace

Skill Marketplace API Handlers.

### `GET` `/api/v1/skills/marketplace/search`

Search skills

### `GET` `/api/v1/skills/marketplace/{skill_id}`

Get skill details

### `GET` `/api/v1/skills/marketplace/{skill_id}/versions`

Get skill versions

### `GET` `/api/v1/skills/marketplace/{skill_id}/ratings`

Get skill ratings

### `POST` `/api/v1/skills/marketplace/publish`

Publish a skill

### `POST` `/api/v1/skills/marketplace/{skill_id}/install`

Install a skill

### `DELETE` `/api/v1/skills/marketplace/{skill_id}/install`

Uninstall a skill

### `POST` `/api/v1/skills/marketplace/{skill_id}/rate`

Rate a skill

### `PUT` `/api/v1/skills/marketplace/{skill_id}/verify`

Set skill verified (admin)

### `DELETE` `/api/v1/skills/marketplace/{skill_id}/verify`

Revoke verification (admin)

### `GET` `/api/v1/skills/marketplace/installed`

List installed skills

### `GET` `/api/v1/skills/marketplace/stats`

Get marketplace statistics

---

## Skills

Skills endpoint handlers.

### `GET` `/api/skills`

List all registered skills

### `GET` `/api/skills/:name`

Get skill details

### `POST` `/api/skills/invoke`

Invoke a skill by name

### `GET` `/api/skills/:name/metrics`

Get skill execution metrics

---

## Slack

Handler for Slack bot integration endpoints.

### `GET` `/api/v1/bots/slack/status`

Build the status response JSON

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `extra_status` | string | Additional fields to include. |

### `GET` `/api/v1/bots/slack/events`

GET /api/v1/bots/slack/events

### `GET` `/api/v1/bots/slack/interactions`

GET /api/v1/bots/slack/interactions

### `GET` `/api/v1/bots/slack/commands`

GET /api/v1/bots/slack/commands

---

## Slo

SLO (Service Level Objective) endpoint handlers.

### `GET` `/api/slos/status`

Overall SLO compliance status

### `GET` `/api/slos/{slo_name}`

Individual SLO details

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

## SMESuccessDashboard

Handler for SME success dashboard endpoints.

### `GET` `/api/v1/sme/success`

Calculate core success metrics for an organization

### `GET` `/api/v1/sme/success/cfo` 🔒

Get CFO-focused success view

### `GET` `/api/v1/sme/success/pm` 🔒

Get PM-focused success view

### `GET` `/api/v1/sme/success/hr` 🔒

Get HR-focused success view

### `GET` `/api/v1/sme/success/milestones` 🔒

Get achievement milestones and gamification status

### `GET` `/api/v1/sme/success/insights` 🔒

Get actionable insights and recommendations

---

## SMEUsageDashboard

Handler for SME usage dashboard endpoints.

### `GET` `/api/v1/usage/summary` 🔒

Get unified usage summary for the SME dashboard

### `GET` `/api/v1/usage/breakdown` 🔒

Get detailed usage breakdown by dimension

### `GET` `/api/v1/usage/roi` 🔒

Get ROI analysis for the organization

### `GET` `/api/v1/usage/export` 🔒

Export usage data in various formats

### `GET` `/api/v1/usage/budget-status`

GET /api/v1/usage/budget-status

### `GET` `/api/v1/usage/forecast` 🔒

Get usage forecast based on current patterns

### `GET` `/api/v1/usage/benchmarks` 🔒

Get industry benchmark comparison data

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

## SpendAnalytics

Handler for spend analytics endpoints.

### `GET` `/api/v1/spend/analytics` 🔒

GET /api/v1/spend/analytics/anomalies

### `GET` `/api/v1/spend/analytics/trend` 🔒

GET /api/v1/spend/analytics/trend

### `GET` `/api/v1/spend/analytics/provider` 🔒

GET /api/v1/spend/analytics/provider

### `GET` `/api/v1/spend/analytics/agent` 🔒

GET /api/v1/spend/analytics/agent

### `GET` `/api/v1/spend/analytics/forecast` 🔒

GET /api/v1/spend/analytics/forecast

### `GET` `/api/v1/spend/analytics/anomalies` 🔒

GET /api/v1/spend/analytics/anomalies

---

## SpendAnalyticsDashboard

Handler for the spend analytics dashboard endpoints.

### `GET` `/api/analytics/spend/summary` 🔒

Return total spend, budget utilization %, and trend direction

### `GET` `/api/analytics/spend/trends` 🔒

Return daily/weekly/monthly spend over time

### `GET` `/api/analytics/spend/by-agent`

GET /api/analytics/spend/by-agent

### `GET` `/api/analytics/spend/by-decision`

GET /api/analytics/spend/by-decision

### `GET` `/api/analytics/spend/budget` 🔒

Return budget limits, remaining, and forecast to exhaustion

---

## SSO

Handler for SSO (Single Sign-On) endpoints.

### `GET` `/auth/sso/login`

GET /auth/sso/login

### `GET` `/auth/sso/callback`

GET /auth/sso/callback

### `GET` `/auth/sso/logout`

GET /auth/sso/logout

### `GET` `/auth/sso/metadata`

GET /auth/sso/metadata

### `GET` `/auth/sso/status`

GET /auth/sso/status

### `GET` `/api/v2/sso/login`

GET /api/v2/sso/login

### `GET` `/api/v2/sso/callback`

GET /api/v2/sso/callback

### `GET` `/api/v2/sso/logout`

GET /api/v2/sso/logout

### `GET` `/api/v2/sso/status`

GET /api/v2/sso/status

### `GET` `/api/v2/sso/metadata`

GET /api/v2/sso/metadata

### `GET` `/api/sso/login`

GET /api/sso/login

### `GET` `/api/sso/callback`

GET /api/sso/callback

### `GET` `/api/sso/logout`

GET /api/sso/logout

### `GET` `/api/sso/status`

GET /api/sso/status

### `GET` `/api/sso/metadata`

GET /api/sso/metadata

---

## Status Page

Public Status Page endpoint handler.

### `GET` `/api/v1/status`

Public service status (no auth required)

---

## System Health

System Health Dashboard handler.

### `GET` `/api/admin/system-health`

Aggregated health overview

### `GET` `/api/admin/system-health/circuit-breakers`

Circuit breaker states

### `GET` `/api/admin/system-health/slos`

SLO compliance status

### `GET` `/api/admin/system-health/adapters`

KM adapter health

### `GET` `/api/admin/system-health/agents`

Agent pool health

### `GET` `/api/admin/system-health/budget`

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

## TemplateDiscovery

Handler for template discovery endpoints.

### `GET` `/api/v1/templates`

GET /api/v1/templates

### `GET` `/api/v1/templates/categories`

Return categories with counts

### `GET` `/api/v1/templates/recommend`

Recommend templates for a given question

### `GET` `/api/v1/templates/*`

GET /api/v1/templates/*

---

## Template Marketplace

Template Marketplace API Handler.

### `GET` `/api/marketplace/templates`

Browse marketplace templates

### `GET` `/api/marketplace/templates/:id`

Get marketplace template details

### `POST` `/api/marketplace/templates`

Publish template to marketplace

### `POST` `/api/marketplace/templates/:id/rate`

Rate a template

### `GET` `/api/marketplace/templates/:id/reviews`

Get template reviews

### `POST` `/api/marketplace/templates/:id/reviews`

Submit a review

### `POST` `/api/marketplace/templates/:id/import`

Import to workspace

### `GET` `/api/marketplace/featured`

Get featured templates

### `GET` `/api/marketplace/trending`

Get trending templates

### `GET` `/api/marketplace/categories`

Get marketplace categories

---

## Threat Intel

Threat Intelligence API Handlers.

### `POST` `/api/v1/threat/url`

Check URL for threats

### `POST` `/api/v1/threat/urls`

Batch check URLs

### `GET` `/api/v1/threat/ip/{ip_address}`

Check IP reputation

### `POST` `/api/v1/threat/ips`

Batch check IPs

### `GET` `/api/v1/threat/hash/{hash_value}`

Check file hash reputation

### `POST` `/api/v1/threat/hashes`

Batch check hashes

### `POST` `/api/v1/threat/email`

Scan email content

### `GET` `/api/v1/threat/status`

Get service status

---

## Tournaments

Tournament-related endpoint handlers.

### `GET` `/api/tournaments`

List all tournaments

### `POST` `/api/tournaments`

Create new tournament

### `GET` `/api/tournaments/{id}`

Get tournament details

### `GET` `/api/tournaments/{id}/standings`

Get tournament standings

### `GET` `/api/tournaments/{id}/bracket`

Get bracket structure

### `GET` `/api/tournaments/{id}/matches`

Get match history

### `POST` `/api/tournaments/{id}/advance`

Advance to next round

### `POST` `/api/tournaments/{id}/matches/{match_id}/result`

Record match result

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

## Transcription

Transcription endpoint handlers for speech-to-text and media processing.

### `POST` `/api/transcription/audio`

Transcribe audio file

### `POST` `/api/transcription/video`

Extract and transcribe audio from video

### `POST` `/api/transcription/youtube`

Transcribe YouTube video

### `GET` `/api/transcription/status/:id`

Get transcription job status

### `GET` `/api/transcription/config`

Get supported formats and limits

---

## Uncertainty

Uncertainty estimation endpoint handlers.

### `POST` `/api/uncertainty/estimate`

Estimate uncertainty for a debate/response

### `GET` `/api/uncertainty/debate/:id`

Get debate uncertainty metrics

### `GET` `/api/uncertainty/agent/:id`

Get agent calibration profile

### `POST` `/api/uncertainty/followups`

Generate follow-up suggestions from cruxes

---

## UsageMetering

Handler for usage metering endpoints.

### `GET` `/api/v1/billing/usage` 🔒

Export usage data as CSV

### `GET` `/api/v1/billing/usage/breakdown` 🔒

Get detailed usage breakdown for billing

### `GET` `/api/v1/billing/usage/summary`

GET /api/v1/billing/usage/summary

### `GET` `/api/v1/billing/usage/export` 🔒

Export usage data as CSV

### `GET` `/api/v1/billing/limits` 🔒

Get current usage limits and utilization percentages

### `GET` `/api/v1/quotas`

GET /api/v1/quotas

### `GET` `/api/v1/quotas/usage` 🔒

Export usage data as CSV

---

## Verticals

Vertical specialist endpoint handlers.

### `GET` `/api/verticals`

List available verticals

### `GET` `/api/verticals/:id`

Get vertical config

### `PUT` `/api/verticals/:id/config`

Update vertical configuration

### `GET` `/api/verticals/:id/tools`

Get vertical tools

### `GET` `/api/verticals/:id/compliance`

Get compliance frameworks

### `POST` `/api/verticals/:id/debate`

Create vertical-specific debate

### `POST` `/api/verticals/:id/agent`

Create specialist agent instance

### `GET` `/api/verticals/suggest`

Suggest vertical for a task

---

## Visualization

Visualization endpoint handlers — argument cartography and replay.

### `GET` `/api/v1/visualization/debates/{id}/graph`

Get argument graph for a debate

### `GET` `/api/v1/visualization/debates/{id}/mermaid`

Get Mermaid diagram

### `GET` `/api/v1/visualization/debates/{id}/html`

Get interactive HTML export

### `GET` `/api/v1/visualization/debates/{id}/statistics`

Get graph statistics

### `POST` `/api/v1/visualization/debates/{id}/replay`

Generate replay artifact

---

## Webhook

Handler for webhook management API endpoints.

### `GET` `/api/v1/webhooks`

Handle GET /api/webhooks - list all webhooks

### `GET` `/api/v1/webhooks/events`

Handle GET /api/webhooks/events - list available event types

### `GET` `/api/v1/webhooks/events/categories`

GET /api/v1/webhooks/events/categories

### `GET` `/api/v1/webhooks/slo/status`

Handle GET /api/webhooks/slo/status - get SLO webhook status

### `GET` `/api/v1/webhooks/slo/test`

Handle POST /api/webhooks/slo/test - send test SLO violation notification

### `GET` `/api/v1/webhooks/dead-letter`

GET /api/v1/webhooks/dead-letter

### `GET` `/api/v1/webhooks/queue/stats`

Handle GET /api/webhooks/queue/stats - get queue statistics

### `GET` `/api/v1/webhooks/bulk`

GET /api/v1/webhooks/bulk

### `GET` `/api/v1/webhooks/pause-all`

GET /api/v1/webhooks/pause-all

### `GET` `/api/v1/webhooks/resume-all`

GET /api/v1/webhooks/resume-all

---

## Workflow Templates

Workflow Templates API Handler.

### `GET` `/api/workflow/templates`

List available templates

### `GET` `/api/workflow/templates/:id`

Get template details

### `GET` `/api/workflow/templates/:id/package`

Get full package

### `POST` `/api/workflow/templates/run`

Execute a template

---

## Workspace Module

Workspace Handler - Enterprise Privacy and Data Isolation APIs.

### `POST` `/api/workspaces`

Create a new workspace

### `GET` `/api/workspaces`

List workspaces

### `GET` `/api/workspaces/{id}`

Get workspace details

### `DELETE` `/api/workspaces/{id}`

Delete workspace

### `POST` `/api/workspaces/{id}/members`

Add member to workspace

### `DELETE` `/api/workspaces/{id}/members/{user_id}`

Remove member

### `GET` `/api/retention/policies`

List retention policies

### `POST` `/api/retention/policies`

Create retention policy

### `PUT` `/api/retention/policies/{id}`

Update retention policy

### `DELETE` `/api/retention/policies/{id}`

Delete retention policy

### `POST` `/api/retention/policies/{id}/execute`

Execute retention policy

### `GET` `/api/retention/expiring`

Get items expiring soon

### `POST` `/api/classify`

Classify content sensitivity

### `GET` `/api/classify/policy/{level}`

Get policy for sensitivity level

### `GET` `/api/audit/entries`

Query audit entries

### `GET` `/api/audit/report`

Generate compliance report

### `GET` `/api/audit/verify`

Verify audit log integrity

---

## Intelligence

HTTP API Handlers for Code Intelligence Analysis.

### `POST` `/api/v1/codebase/{repo}/analyze`

Analyze codebase structure

### `GET` `/api/v1/codebase/{repo}/symbols`

List symbols (classes, functions)

### `GET` `/api/v1/codebase/{repo}/callgraph`

Get call graph

### `GET` `/api/v1/codebase/{repo}/deadcode`

Find dead/unreachable code

### `POST` `/api/v1/codebase/{repo}/impact`

Analyze impact of changes

### `POST` `/api/v1/codebase/{repo}/understand`

Answer questions about code

### `POST` `/api/v1/codebase/{repo}/audit`

Run comprehensive audit

---

## Metrics

HTTP API Handlers for Codebase Metrics Analysis.

### `POST` `/api/v1/codebase/{repo}/metrics/analyze`

Run metrics analysis

### `GET` `/api/v1/codebase/{repo}/metrics`

Get latest metrics

### `GET` `/api/v1/codebase/{repo}/metrics/{analysis_id}`

Get specific analysis

### `GET` `/api/v1/codebase/{repo}/hotspots`

Get complexity hotspots

### `GET` `/api/v1/codebase/{repo}/duplicates`

Get code duplicates

---

## Quick Scan

Quick Security Scan API Handler.

### `POST` `/api/codebase/quick-scan`

Run quick security scan

### `GET` `/api/codebase/quick-scan/{scan_id}`

Get scan result

---

## Audit Bridge

Audit-to-GitHub Bridge Handler.

### `POST` `/api/v1/github/audit/issues`

Create issues from findings

### `POST` `/api/v1/github/audit/issues/bulk`

Bulk create issues

### `POST` `/api/v1/github/audit/pr`

Create PR with fixes

### `GET` `/api/v1/github/audit/sync/{session_id}`

Get sync status

### `POST` `/api/v1/github/audit/sync/{session_id}`

Sync session to GitHub

---

## Pr Review

HTTP API Handlers for GitHub Pull Request Review.

### `POST` `/api/v1/github/pr/review`

Trigger PR review

### `GET` `/api/v1/github/pr/{pr_number}`

Get PR details

### `POST` `/api/v1/github/pr/{pr_number}/review`

Submit review

### `GET` `/api/v1/github/pr/{pr_number}/reviews`

List reviews

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
