/**
 * SDK Namespace APIs
 *
 * Re-exports all namespace APIs for the Aragora SDK.
 */

export {
  DebatesAPI,
  type DebateImpasse,
  type RhetoricalObservation,
  type RhetoricalAnalysis,
  type TricksterStatus,
  type MetaCritique,
  type DebateSummary,
  type VerificationReport,
  type ClaimVerification,
  type FollowupSuggestion,
  type ForkInfo,
  type DebateSearchOptions,
  type BatchJob,
  type BatchSubmission,
  type DebateGraph,
  type GraphBranch,
  type MatrixComparison,
} from './debates';
export { AgentDashboardAPI } from './agent-dashboard';
export {
  AgentBridgeAPI,
  type AgentBridgeRunListResponse,
  type AgentBridgeRun,
  type ListAgentBridgeRunsOptions,
} from './agent-bridge';
export { AgentsAPI } from './agents';
export { WorkflowsAPI } from './workflows';
export { SMEAPI } from './sme';
export { ControlPlaneAPI } from './control-plane';
export {
  CoordinationAPI,
  type RegisterWorkspaceRequest,
  type FederatedWorkspace,
  type CreateFederationPolicyRequest,
  type FederationPolicy,
  type ExecuteCrossWorkspaceRequest,
  type CrossWorkspaceResult,
  type GrantConsentRequest,
  type DataSharingConsent,
  type ApproveRequestBody,
  type CoordinationStats,
  type CoordinationHealth,
} from './coordination';
export { ModerationAPI } from './moderation';
export { AudienceAPI } from './audience';
export { ModesAPI } from './modes';
export { SpectateAPI } from './spectate';
export { GauntletAPI } from './gauntlet';
export type { GauntletRunRequest } from '../types';
export {
  AnalyticsAPI,
  type AnalyticsPeriodOptions,
  type DecisionAnalyticsOutcomesOptions,
  type DecisionAnalyticsPeriodOptions,
} from './analytics';
export { MemoryAPI, type MemoryStoreOptions, type MemoryRetrieveOptions } from './memory';
export { RBACAPI, type CreateRoleRequest, type UpdateRoleRequest } from './rbac';
export { KnowledgeAPI, type KnowledgeSearchOptions, type KnowledgeMoundQueryOptions } from './knowledge';
export { TournamentsAPI, type MatchResultSubmission } from './tournaments';
export { AuthAPI, type SessionInfo, type ApiKeyInfo, type OAuthProviderInfo } from './auth';
export { VerificationAPI, type DebateConclusionVerifyOptions } from './verification';
export { AuditAPI, type AuditEventFilterOptions, type AuditExportOptions } from './audit';
export { TenantsAPI } from './tenants';
export { OrganizationsAPI } from './organizations';

// SME Starter Pack APIs
export { BillingAPI, type BillingPlan, type BillingUsage, type Subscription, type UsageForecast } from './billing';
export { BudgetsAPI, type Budget, type BudgetAlert, type BudgetSummary, type CreateBudgetRequest, type UpdateBudgetRequest } from './budgets';
export { ReceiptsAPI, type DecisionReceipt, type GauntletReceiptExport } from './receipts';
export { ExplainabilityAPI, type ExplainabilityResult, type ExplanationFactor, type CounterfactualScenario, type Provenance, type Narrative } from './explainability';

// Enterprise APIs
export { WebhooksAPI, type Webhook, type WebhookEvent, type WebhookDelivery, type WebhookSLOStatus, type CreateWebhookRequest, type UpdateWebhookRequest } from './webhooks';
export { PluginsAPI, type Plugin, type PluginListing, type PluginSubmission, type PluginConfigSchema, type InstallPluginRequest, type PluginQueryRequest, type PluginValidateRequest } from './plugins';
export { WorkspacesAPI, type Workspace, type WorkspaceSettings, type CreateWorkspaceRequest } from './workspaces';
export {
  IntegrationsAPI,
  type Integration,
  type AvailableIntegration,
  type IntegrationConfigSchema,
  type IntegrationSyncStatus,
  type CreateIntegrationRequest,
  type UpdateIntegrationRequest,
  // Zapier types
  type ZapierApp,
  type ZapierAppSummary,
  type ZapierTrigger,
  type ZapierTriggerSubscription,
  type CreateZapierAppRequest,
  type SubscribeZapierTriggerRequest,
  // Make types
  type MakeConnection,
  type MakeConnectionSummary,
  type MakeWebhook,
  type MakeModule,
  type CreateMakeConnectionRequest,
  type RegisterMakeWebhookRequest,
  // n8n types
  type N8nCredential,
  type N8nCredentialSummary,
  type N8nWebhook,
  type N8nNode,
  type N8nNodesResponse,
  type CreateN8nCredentialRequest,
  type RegisterN8nWebhookRequest,
} from './integrations';

// Compliance (SOC 2, GDPR, Audit)
export {
  ComplianceAPI,
  type AuditEventType,
  type ComplianceStatus,
  type Soc2Report,
  type Soc2ControlAssessment,
  type Soc2Finding,
  type GdprExportResult,
  type GdprDeletionResult,
  type AuditVerificationResult,
  type AuditAnomaly,
  type AuditEvent,
  type AuditEventsExport,
} from './compliance';

// Connectors (Data Source Integrations)
export {
  ConnectorsAPI,
  type ConnectorType,
  type SyncFrequency,
  type SyncStatus,
  type HealthStatus as ConnectorHealthStatus,
  type Connector,
  type SyncOperation,
  type ConnectionTestResult,
  type ConnectorHealth as ConnectorHealthDetails,
  type PaginationInfo as ConnectorsPaginationInfo,
} from './connectors';

// Marketplace
export {
  MarketplaceAPI,
  type DeploymentStatus,
  type MarketplaceListParams,
  type TemplateDeployment,
  type TemplateRatings,
} from './marketplace';
export { MCPAPI } from './mcp';

export {
  PromptEngineAPI,
  type PromptEngineRunListOptions,
  type PromptEngineRunRequest,
  type PromptEnginePromptRequest,
  type PromptEngineIntentRequest,
  type PromptEngineInterrogateRequest,
  type PromptEngineSpecifyRequest,
  type PromptEngineValidateRequest,
} from './prompt-engine';

// Codebase Analysis
export { CodebaseAPI } from './codebase';

// Consensus & Detection
export {
  ConsensusAPI,
  type SimilarDebate,
  type SimilarDebatesResponse,
  type SettledTopic,
  type SettledTopicsResponse,
  type ConsensusStats,
  type DissentView,
  type DissentsResponse,
  type ContrarianView,
  type ContrariansResponse,
  type RiskWarning,
  type WarningsResponse,
  type DomainHistoryEntry,
  type DomainHistoryResponse,
  type FindSimilarOptions,
  type SettledOptions,
  type FilterOptions,
} from './consensus';

// OAuth Authentication
export {
  OAuthAPI,
  type OAuthProvider,
  type OAuthProviderConfig,
  type OAuthCallbackResponse,
  type LinkedOAuthAccount,
  type ProvidersResponse,
  type LinkedProvidersResponse,
  type LinkAccountRequest,
  type LinkAccountResponse,
  type UnlinkAccountRequest,
  type UnlinkAccountResponse,
  type AuthorizationUrlResponse,
} from './oauth';

// Monitoring & Anomaly Detection
export {
  MonitoringAPI,
  type TrendDirection,
  type AnomalySeverity,
  type MetricTrend,
  type TrendSummary,
  type Anomaly,
  type BaselineStats,
  type RecordMetricResponse,
  type GetTrendResponse,
  type GetAllTrendsResponse,
  type GetAnomaliesResponse,
  type GetBaselineResponse,
  type RecordMetricOptions,
  type GetAnomaliesOptions,
} from './monitoring';
export { SettlementAPI, type SettlementBatchItem } from './settlements';

// System Administration
export {
  SystemAPI,
  type MaintenanceTask,
  type CircuitBreakerStatus,
  type CycleEntry,
  type EventEntry,
  type DebateHistoryEntry,
  type CircuitBreakerMetrics,
  type AuthStats,
  type MaintenanceResult,
  type DebugTestResponse,
  type CyclesResponse,
  type EventsResponse,
  type DebateHistoryResponse,
  type CircuitBreakersResponse,
  type RevokeTokenResponse,
  type HistoryOptions,
} from './system';

// Nomic Loop Control
export {
  NomicAPI,
  type NomicHealthStatus,
  type NomicPhase,
  type NomicState,
  type NomicHealth,
  type NomicMetrics,
  type NomicLogResponse,
  type RiskEntry,
  type RiskRegisterResponse,
  type Proposal,
  type ProposalsResponse,
  type StartLoopRequest,
  type StopLoopRequest,
  type ApproveProposalRequest,
  type RejectProposalRequest,
  type OperationalMode,
  type ModesResponse,
} from './nomic';

// Cross-Pollination
export {
  CrossPollinationAPI,
  type CrossPollinationStats,
  type CrossPollinationSubscriber,
  type CrossPollinationBridge,
  type CrossPollinationMetrics,
  type KMIntegrationStatus,
  type KMSyncResult,
  type KMStalenessResult,
  type CulturePattern,
  type WorkspaceCulture,
} from './cross-pollination';

// Unified Decisions
export {
  DecisionsAPI,
  type DecisionType,
  type DecisionPriority,
  type DecisionStatus,
  type ResponseChannel,
  type DecisionContext,
  type DecisionConfig,
  type DecisionRequest,
  type DecisionResult,
  type DecisionStatusResponse,
  type DecisionSummary,
  type DecisionListResponse,
} from './decisions';

// Critiques
export {
  CritiquesAPI,
  type Critique,
  type CritiquePattern,
  type ArchivedCritique,
} from './critiques';

// Belief Network
export {
  BeliefNetworkAPI,
  type Crux,
  type LoadBearingClaim,
  type BeliefNode,
  type BeliefEdge,
} from './belief-network';

// Moments
export {
  MomentsAPI,
  type Moment,
  type MomentsSummary,
  type MomentsTimeline,
  type TrendingMoments,
} from './moments';

// Introspection
export {
  IntrospectionAPI,
  type AgentInfo,
  type LeaderboardEntry,
  type SystemIntrospection,
} from './introspection';

// Documents
export {
  DocumentsAPI,
  type Document,
  type DocumentFormat,
  type UploadResult,
} from './documents';

// Retention
export {
  RetentionAPI,
  type RetentionPolicy,
  type ExpiringItem,
  type ExecutionResult,
} from './retention';

// Notifications
export {
  NotificationsAPI,
  type NotificationChannel,
  type NotificationEventType,
  type IntegrationStatus,
  type EmailConfig,
  type TelegramConfig,
  type EmailRecipient,
  type NotificationDelivery,
} from './notifications';

// Pulse (Trending Topics)
export {
  PulseAPI,
  type PulseSource,
  type TrendingTopic,
  type DebateSuggestion,
  type PulseAnalytics,
  type SchedulerStatus,
  type SchedulerConfig,
  type ScheduledDebate,
} from './pulse';

// Leaderboard
export {
  LeaderboardAPI,
  type RankingEntry,
  type AgentPerformance,
  type HeadToHead,
  type DomainLeaderboard,
  type LeaderboardView,
} from './leaderboard';

// Policies
export {
  PoliciesAPI,
  type PolicyType,
  type PolicySeverity,
  type PolicyAction,
  type Policy,
  type PolicyRule,
  type PolicyViolation,
  type ComplianceSummary,
  type CreatePolicyRequest,
  type UpdatePolicyRequest,
} from './policies';

// Replays
export {
  ReplaysAPI,
  type ReplayEventType,
  type ReplaySummary,
  type ReplayEvent,
  type Replay,
  type EvolutionEntry,
  type ReplayFork,
} from './replays';

// Cost Management
export {
  CostManagementAPI,
  type CostBreakdownItem,
  type DailyCost,
  type CostAlert,
  type CostSummary,
  type CostBudget,
  type CostRecommendation,
  type EfficiencyMetrics,
  type CostForecast,
  type TimeRange,
  type GroupBy,
} from './cost-management';

// Onboarding
export {
  OnboardingAPI,
  type StarterTemplate,
  type OnboardingFlow,
  type QuickStartConfig,
  type OnboardingAnalytics,
  type QuickStartProfile,
  type FlowAction,
} from './onboarding';

// Deliberations
export {
  DeliberationsAPI,
  type Deliberation,
  type DeliberationStatus,
  type DeliberationStats,
  type ActiveDeliberationsResponse,
  type DeliberationStreamConfig,
} from './deliberations';

// Genesis (Evolution Visibility)
export {
  GenesisAPI,
  type GenesisEventType,
  type GenesisEvent,
  type GenesisStats,
  type Genome,
  type LineageNode,
  type DescendantNode,
  type Population,
  type DebateTree,
  type ListEventsOptions,
  type ListGenomesOptions,
} from './genesis';

// Laboratory (Persona Lab)
export {
  LaboratoryAPI,
  type EmergentTrait,
  type CrossPollinationSuggestion,
  type EmergentTraitsResponse,
  type CrossPollinationResponse,
  type EmergentTraitsOptions,
  type CrossPollinationRequest,
} from './laboratory';

// Teams Bot Integration
export {
  TeamsAPI,
  type TeamsBotStatus,
  type TeamsTenant,
  type TeamsInstallResponse,
  type TeamsOAuthResult,
  type TeamsChannel,
  type TeamsNotificationSettings,
  type TeamsDebateMessage,
} from './teams';

// Learning (Meta-Learning Analytics)
export {
  LearningAPI,
  type LearningEvolutionResponse,
} from './learning';

// Training (SFT/DPO exports, jobs)
export {
  TrainingAPI,
  type ExportFormat,
  type ExportType,
  type JobStatus,
  type GauntletPersona as TrainingGauntletPersona,
  type SFTExportParams,
  type DPOExportParams,
  type GauntletExportParams,
  type SFTRecord,
  type DPORecord,
  type TrainingExportResult,
  type TrainingStats,
  type TrainingFormats,
  type TrainingJob,
  type TrainingJobDetails,
  type ListJobsParams,
  type CompleteJobData,
  type TrainingMetrics,
  type TrainingArtifacts,
} from './training';

// Batch Operations
export {
  BatchAPI,
  type BatchItem,
  type BatchItemStatus,
  type BatchStatus,
  type BatchSubmitRequest,
  type BatchSubmitResponse,
  type BatchItemResult,
  type BatchStatusResponse,
  type BatchSummary,
  type QueueStatus,
  type ListBatchesOptions,
} from './batch';

// Email Integrations
export {
  GmailAPI,
  type GmailConnection,
  type EmailTriageRule,
  type EmailDebateConfig,
  type ProcessedEmail,
  type GmailStats,
  type OAuthInitResponse,
  type SyncResult,
  type CreateTriageRuleRequest,
  type UpdateTriageRuleRequest,
  type CreateDebateConfigRequest,
} from './gmail';

export {
  OutlookAPI,
  type OutlookOAuthResponse,
  type OutlookAuthResult,
  type OutlookStatus,
  type MailFolder,
  type MessageSummary,
  type Message,
  type Attachment,
  type Conversation,
  type SendMessageRequest,
  type ReplyMessageRequest,
  type ListMessagesParams,
} from './outlook';

// Email Priority
export {
  EmailPriorityAPI,
  type ScoringTier,
  type UserAction,
  type EmailCategory,
  type GmailScopes,
  type EmailMessage,
  type PriorityFactor,
  type PriorityResult,
  type CategoryResult,
  type CategoryStats,
  type EmailConfig as EmailPriorityConfig,
  type FeedbackItem,
  type InboxItem,
  type InboxParams,
  type CrossChannelContext,
  type ContextBoost,
} from './email-priority';

// Accounting & Payroll
export {
  AccountingAPI,
  type Company,
  type FinancialStats,
  type Customer,
  type Transaction,
  type AccountingStatus,
  type FinancialReport,
  type ReportRequest,
  type Employee,
  type PayrollRun,
  type PayrollDetails,
  type JournalEntry,
  type ListCustomersParams,
  type ListTransactionsParams,
} from './accounting';

// Payments
export {
  PaymentsAPI,
  type PaymentProvider,
  type PaymentStatus,
  type SubscriptionInterval,
  type BillingAddress,
  type PaymentMethodDetails,
  type ChargeRequest,
  type AuthorizeRequest,
  type RefundRequest,
  type PaymentResult,
  type TransactionDetails,
  type CustomerProfile,
  type PaymentMethodSummary,
  type CreateCustomerRequest,
  type UpdateCustomerRequest,
  type Subscription as PaymentSubscription,
  type CreateSubscriptionRequest,
  type UpdateSubscriptionRequest,
} from './payments';

// Unified Inbox (Multi-Account Email)
export {
  UnifiedInboxAPI,
  type EmailProvider,
  type AccountStatus,
  type TriageAction,
  type PriorityTier,
  type ConnectedAccount,
  type UnifiedMessage,
  type TriageResult,
  type InboxStats,
  type InboxTrends,
  type OAuthUrlResponse,
  type ConnectAccountRequest,
  type ListMessagesParams as UnifiedInboxListParams,
  type TriageRequest,
  type BulkAction,
  type BulkActionRequest,
} from './unified-inbox';

// Expenses
export {
  ExpensesAPI,
  type ExpenseCategory,
  type ExpenseStatus,
  type PaymentMethod,
  type Expense,
  type UploadReceiptRequest,
  type CreateExpenseRequest,
  type UpdateExpenseRequest,
  type ListExpensesParams,
  type ExpenseStats,
  type SyncResult as ExpenseSyncResult,
  type CategorizeResult,
} from './expenses';

// Threat Intelligence
export {
  ThreatIntelAPI,
  type ThreatSeverity,
  type ThreatType,
  type HashType,
  type URLCheckResult,
  type URLBatchSummary,
  type IPReputationResult,
  type IPBatchSummary,
  type HashCheckResult,
  type HashBatchSummary,
  type EmailScanResult,
  type ThreatIntelStatus,
  type CheckURLRequest,
  type CheckURLsBatchRequest,
  type CheckIPsBatchRequest,
  type CheckHashesBatchRequest,
  type ScanEmailRequest,
} from './threat-intel';

// Devices & Push Notifications
export {
  DevicesAPI,
  type DeviceType,
  type NotificationStatus,
  type DeviceRegistration,
  type Device,
  type NotificationMessage,
  type NotificationResult,
  type UserNotificationResult,
  type ConnectorHealth,
  type AlexaRequest,
  type AlexaResponse,
  type GoogleActionsRequest,
  type GoogleActionsResponse,
} from './devices';

// Privacy (GDPR/CCPA)
export {
  PrivacyAPI,
  type DataCategory,
  type ThirdPartySharing,
  type DataInventory,
  type PrivacyPreferences,
  type ExportMetadata,
  type DataExport,
  type AccountDeletionResponse,
  type AccountDeletionRequest,
} from './privacy';

// Feedback (NPS & User Feedback)
export {
  FeedbackAPI,
  type FeedbackType,
  type NPSSubmission,
  type FeedbackSubmission,
  type FeedbackResponse,
  type NPSSummary,
  type FeedbackPrompt,
} from './feedback';

// Code Review
export {
  CodeReviewAPI,
  type FindingSeverity,
  type FindingCategory,
  type ReviewFinding,
  type ReviewResult,
  type CodeReviewRequest,
  type DiffReviewRequest,
  type PRReviewRequest,
  type SecurityScanResult,
  type ReviewHistoryResponse,
} from './code-review';

// RLM (Recursive Language Models)
export {
  RLMAPI,
  type RLMStrategy,
  type SourceType,
  type StreamMode,
  type StrategyInfo,
  type CompressionResult,
  type QueryResult,
  type ContextSummary,
  type ContextDetails,
  type StreamChunk,
  type RLMStats,
} from './rlm';

// Backups (Disaster Recovery)
export {
  BackupsAPI,
  type BackupType,
  type BackupStatus,
  type Backup,
  type VerificationResult,
  type ComprehensiveVerificationResult,
  type RetentionPolicy as BackupRetentionPolicy,
  type BackupStats,
} from './backups';

// Dashboard
export {
  DashboardAPI,
  type DashboardDebateEntry,
} from './dashboard';

// AP Automation (Accounts Payable)
export {
  APAutomationAPI,
  type PaymentPriority,
  type APPaymentMethod,
  type APInvoiceStatus,
  type APInvoice,
  type AddAPInvoiceRequest,
  type RecordAPPaymentRequest,
  type ListAPInvoicesParams,
  type OptimizePaymentsRequest,
  type PaymentScheduleEntry,
  type PaymentSchedule,
  type BatchPaymentRequest,
  type BatchPayment,
  type CashFlowEntry,
  type CashFlowForecast,
  type DiscountOpportunity,
} from './ap-automation';

// AR Automation (Accounts Receivable)
export {
  ARAutomationAPI,
  type ARInvoiceStatus,
  type ReminderLevel,
  type ARLineItem,
  type ARInvoice,
  type CreateARInvoiceRequest,
  type ListARInvoicesParams,
  type RecordARPaymentRequest,
  type AgingBucket,
  type AgingReport,
  type CollectionActionType,
  type CollectionSuggestion,
  type AddARCustomerRequest,
  type CustomerBalance,
} from './ar-automation';

// Invoice Processing (OCR & Approval Workflows)
export {
  InvoiceProcessingAPI,
  type InvoiceProcessingStatus,
  type AnomalySeverity as InvoiceAnomalySeverity,
  type InvoiceLineItem,
  type ProcessedInvoice,
  type InvoiceAnomaly,
  type CreateInvoiceRequest,
  type ListInvoicesParams,
  type POMatch,
  type SchedulePaymentRequest,
  type ScheduledPayment,
  type InvoiceStats,
  type PurchaseOrder,
  type CreatePORequest,
} from './invoice-processing';

// Playground
export { PlaygroundAPI } from './playground';

// Skills
export {
  SkillsAPI,
  type SkillCapability,
  type SkillStatus,
  type SkillManifest,
  type SkillDetails,
  type SkillMetrics,
  type InvokeSkillRequest,
  type InvokeSkillResult,
} from './skills';

// Usage Metering
export {
  UsageMeteringAPI,
  type UsagePeriod,
  type BillingTier,
  type UsageExportFormat,
  type TokenUsage,
  type UsageCounts,
  type UsageSummary,
  type ModelUsage,
  type ProviderUsage,
  type DailyUsage,
  type UserUsage,
  type UsageBreakdown,
  type UsageLimits,
  type QuotaPeriod,
  type QuotaStatus,
  type QuotasResponse,
  type UsageBreakdownOptions,
  type UsageExportOptions,
} from './usage-metering';

// Transcription
export {
  TranscriptionAPI,
  type TranscriptionStatus,
  type TranscriptionBackend,
  type WhisperModel,
  type TranscriptionConfig,
  type TranscriptionFormats,
  type TranscriptionSegment,
  type TranscriptionResult,
  type TranscriptionJob,
  type JobStatusResponse,
  type SegmentsResponse,
  type YouTubeVideoInfo,
  type TranscriptionOptions,
  type YouTubeTranscriptionOptions,
  type UploadResponse,
} from './transcription';

// Email Services (Follow-up, Snooze, Category Learning)
export {
  EmailServicesAPI,
  type FollowUpStatus,
  type FollowUpPriority,
  type SnoozeReason,
  type EmailServiceCategory,
  type FollowUpItem,
  type MarkFollowUpRequest,
  type PendingFollowUpsOptions,
  type PendingFollowUpsResponse,
  type ResolveFollowUpRequest,
  type ResolveFollowUpResponse,
  type CheckRepliesResponse,
  type AutoDetectResponse,
  type SnoozeSuggestion,
  type SnoozeSuggestionsOptions,
  type SnoozeSuggestionsResponse,
  type SnoozeEmailResponse,
  type SnoozedEmail,
  type SnoozedEmailsResponse,
  type ProcessDueSnoozesResponse,
  type CategoryInfo,
  type CategoryFeedbackRequest,
  type CategoryFeedbackResponse,
} from './email-services';

// Persona (Agent Identity Management)
export {
  PersonaAPI,
  type PersonaTrait,
  type ExpertiseDomain,
  type IdentitySection,
  type Persona,
  type GroundedPersona,
  type PersonaOptions,
  type PerformanceSummary,
  type DomainExpertise,
  type PositionAccuracy,
  type IdentityPrompt,
  type CreatePersonaRequest,
  type UpdatePersonaRequest,
} from './persona';

// Verticals (Domain Specialists)
export {
  VerticalsAPI,
  type VerticalId,
  type ComplianceLevel,
  type ModelConfig,
  type ToolConfig,
  type ComplianceRule,
  type ComplianceFramework,
  type VerticalSummary,
  type VerticalDetails,
  type VerticalSuggestion,
  type CreateVerticalAgentRequest,
  type CreateVerticalAgentResponse,
  type CreateVerticalDebateRequest,
  type CreateVerticalDebateResponse,
  type UpdateVerticalConfigRequest,
} from './verticals';

// Admin (Platform Administration)
export {
  AdminAPI,
  type Organization as AdminOrganization,
  type OrganizationList,
  type AdminUser,
  type AdminUserList,
  type PlatformStats,
  type RevenueData,
  type NomicStatus,
  type SecurityStatus,
  type SecurityKey,
} from './admin';

// Routing (Team Selection & Rules)
export {
  RoutingAPI,
  type ConditionOperator,
  type ActionType,
  type MatchMode,
  type AgentRecommendation,
  type TeamComposition,
  type DomainDetection,
  type DomainLeaderboardEntry,
  type RuleCondition,
  type RuleAction,
  type RoutingRule,
  type RuleEvaluationResult,
  type RuleTemplate,
  type BestTeamsOptions,
  type RecommendationsRequest,
  type AutoRouteRequest,
  type AutoRouteResponse,
  type CreateRuleRequest as CreateRoutingRuleRequest,
  type UpdateRuleRequest as UpdateRoutingRuleRequest,
  type ListRulesOptions,
  type EvaluateRulesRequest,
} from './routing';

// Relationships (Agent Network)
export {
  RelationshipsNamespace,
  type AgentRelationship,
  type RelationshipNode,
  type RelationshipEdge,
  type RelationshipGraph,
  type RelationshipStats,
  type RelationshipSummary,
} from './relationships';

// YouTube (Video Publishing)
export {
  YouTubeNamespace,
  type YouTubePublishRequest,
  type YouTubePublishResponse,
  type YouTubeAuthStatus,
  type YouTubeAuthUrl,
} from './youtube';

// Podcast (Audio Content)
export {
  PodcastNamespace,
  type PodcastEpisode,
  type PodcastFeed,
  type GenerateEpisodeOptions,
} from './podcast';

// History (Historical Data)
export {
  HistoryNamespace,
  type HistoricalDebate,
  type NomicCycle,
  type HistoricalEvent,
  type HistorySummary,
  type HistoryQueryOptions,
} from './history';

// Ranking (ELO Rankings)
export {
  RankingNamespace,
  type AgentRanking,
  type RankingStats,
  type RankingQueryOptions,
} from './ranking';

// Health (System Health)
export {
  HealthNamespace,
  type HealthStatus,
  type DetailedHealthStatus,
  type HealthCheck,
  type ComponentHealth,
} from './health';

// Advertising (Platform Integrations)
export {
  AdvertisingAPI,
  type AdvertisingPlatform,
  type Campaign,
  type CampaignTargeting,
  type PerformanceMetrics,
  type BudgetRecommendation,
  type AnalysisResult,
  type ConnectPlatformRequest,
  type CreateCampaignRequest,
  type UpdateCampaignRequest,
  type AnalyzeRequest,
} from './advertising';

// A2A (Agent-to-Agent Protocol)
export {
  A2AAPI,
  type AgentCard,
  type A2AAgent,
  type A2ATask,
  type SubmitTaskRequest,
  type StreamTaskRequest,
  type StreamChunk as A2AStreamChunk,
} from './a2a';

// Metrics (System & Application Metrics)
export {
  MetricsAPI,
  type HealthMetrics,
  type CacheMetrics,
  type SystemMetrics as MetricsSystemMetrics,
  type ApplicationMetrics,
  type DebateMetrics,
} from './metrics';

// Queue
export { QueueAPI, type QueueJob, type QueueStats, type QueueWorker } from './queue';

// Chat (Knowledge Chat)
export {
  ChatAPI,
  type KnowledgeSearchScope,
  type KnowledgeRelevanceStrategy,
  type ChatMessage,
  type ChatKnowledgeSearchRequest,
  type ChatKnowledgeSearchResponse,
  type ChatKnowledgeInjectRequest,
  type ChatKnowledgeInjectResponse,
  type ChatKnowledgeStoreRequest,
  type ChatKnowledgeStoreResponse,
  type ChatKnowledgeSummaryResponse,
  type KnowledgeContextItem,
} from './chat';

// Flips
export { FlipsAPI, type FlipEntry, type FlipSummary } from './flips';

// Insights
export { InsightsAPI, type InsightEntry, type ExtractDetailedRequest } from './insights';

// Classify
export { ClassifyAPI, type ClassifyRequest, type ClassifyResponse } from './classify';

// Calibration
export { CalibrationAPI, type CalibrationLeaderboardEntry } from './calibration';

// Matches
export { MatchesAPI, type MatchEntry } from './matches';

// Reputation
export { ReputationAPI, type ReputationEntry } from './reputation';

// Evolution
export { EvolutionAPI, type EvolutionHistoryEntry, type EvolutionHistoryResponse } from './evolution';

// OpenAPI
export { OpenApiAPI } from './openapi';

// Probes
export { ProbesAPI, type CapabilityProbeRequest, type CapabilityProbeResponse } from './probes';

// Belief Network (Cruxes & Provenance)
export {
  BeliefAPI,
  type BeliefCrux,
  type BeliefCruxes,
  type LoadBearingClaim as BeliefLoadBearingClaim,
  type LoadBearingClaims as BeliefLoadBearingClaims,
  type BeliefGraphNode,
  type BeliefGraphLink,
  type BeliefGraph,
  type ExportFormat as BeliefExportFormat,
  type BeliefExport,
} from './belief';

// Bots (Platform Integrations)
export {
  BotsAPI,
  type BotStatus,
  type TeamsStatus,
  type DiscordStatus,
  type TelegramStatus,
  type WhatsAppStatus,
  type GoogleChatStatus,
  type ZoomStatus,
  type SlackStatus,
  type AllBotStatus,
} from './bots';

// Usage (SME Dashboard)
export {
  UsageAPI,
  type UsagePeriod as UsageDashboardPeriod,
  type BenchmarkType,
  type ExportFormat as UsageDashboardExportFormat,
  type GroupByDimension,
  type UsageSummary as UsageDashboardSummary,
  type UsageBreakdown as UsageDashboardBreakdown,
  type ROIAnalysis,
  type BudgetStatus,
  type UsageForecast as UsageDashboardForecast,
  type IndustryBenchmarks,
  type UsageExport,
} from './usage';

// OAuth Wizard (SME Onboarding)
export {
  OAuthWizardAPI,
  type ProviderCategory,
  type ConfigStatus,
  type OAuthProvider as WizardOAuthProvider,
  type ProviderStatus,
  type WizardConfig,
  type ValidationResult,
  type PreflightCheck,
  type IntegrationStatusSummary,
} from './oauth-wizard';

// SLO (Service Level Objectives)
export {
  SLONamespace,
  type SLOTarget,
  type SLOStatus,
  type ErrorBudget,
  type SLOViolation,
  type OverallSLOStatus,
  type SLOAlert,
} from './slo';

// SSO (Single Sign-On)
export {
  SSONamespace,
  type SSOProviderType,
  type SSOLoginResponse,
  type SSOUser,
  type SSOCallbackResult,
  type SSOStatus,
  type SAMLMetadata,
  type SSOLogoutResponse,
} from './sso';

// Email Debate (AI-Powered Email Prioritization)
export {
  EmailDebateNamespace,
  type EmailInput,
  type PriorityLevel,
  type PrioritizationResult,
  type BatchPrioritizationResult,
  type EmailCategory as EmailDebateCategory,
  type TriageResult as EmailTriageResult,
  type InboxTriageResponse,
} from './email-debate';

// Facts (Knowledge CRUD)
export {
  FactsAPI,
  type Fact,
  type Relationship,
  type RelationshipType,
  type CreateFactRequest,
  type UpdateFactRequest,
  type ListFactsOptions,
  type PaginatedFacts,
  type SearchOptions,
  type SearchedFact,
  type CreateRelationshipRequest,
  type UpdateRelationshipRequest,
  type GetRelationshipsOptions,
  type BatchCreateResponse,
  type BatchDeleteResponse,
  type FactStats,
} from './facts';

// Evaluation (LLM-as-Judge)
export {
  EvaluationAPI,
  type EvaluationDimension,
  type EvaluationProfile,
  type EvaluateRequest,
  type EvaluationResult,
  type CompareRequest,
  type ComparisonResult,
} from './evaluation';

// Disaster Recovery
export {
  DisasterRecoveryAPI,
  type DRStatus,
  type DRIssue,
  type DRObjectives,
  type DRDrillRequest,
  type DRDrillResult,
  type DRDrillStep,
  type DRValidateRequest,
  type DRValidationResult,
  type DRValidationCheck,
} from './disaster-recovery';

// Repository Indexing
export {
  RepositoryAPI,
  type IndexRepositoryRequest,
  type IndexRepositoryResponse,
  type IncrementalIndexRequest,
  type IndexStatus,
  type CodeEntity,
  type EntityRelationship,
  type RepositoryGraph,
  type EntityFilterParams,
  type BatchIndexRequest,
  type BatchIndexResponse,
} from './repository';

// Dependency Analysis
export {
  DependencyAnalysisAPI,
  type AnalyzeDependenciesRequest,
  type Dependency,
  type DependencyAnalysisResult,
  type GenerateSBOMRequest,
  type SBOMResult,
  type SBOMComponent,
  type SBOMRelationship,
  type ScanVulnerabilitiesRequest,
  type Vulnerability,
  type VulnerabilityScanResult,
  type CheckLicensesRequest,
  type LicenseInfo,
  type LicenseCheckResult,
} from './dependency-analysis';

// Agent Selection
export {
  AgentSelectionAPI,
  type AgentSelectionClientInterface,
  type SelectionPlugin,
  type ScorerPlugin,
  type TeamSelectorPlugin,
  type RoleAssignerPlugin,
  type DefaultPluginConfig,
  type ListPluginsResponse,
  type ScoreAgentsRequest,
  type AgentScore,
  type ScoreAgentsResponse,
  type GetBestAgentRequest,
  type GetBestAgentResponse,
  type SelectTeamRequest,
  type TeamMember,
  type SelectTeamResponse,
  type AssignRolesRequest,
  type RoleAssignment,
  type AssignRolesResponse,
  type SelectionHistoryEntry,
  type SelectionHistoryResponse,
} from './agent-selection';

// Computer Use (Safe Computer Control)
export {
  ComputerUseAPI,
  type TaskStatus as ComputerUseTaskStatus,
  type ActionType as ComputerUseActionType,
  type ComputerUseTask,
  type ComputerUseStep,
  type ActionStats,
  type ComputerUsePolicy,
  type CreateTaskOptions,
  type ListTasksOptions,
  type CreatePolicyOptions,
  type UpdatePolicyOptions,
  type ExecuteActionOptions,
} from './computer-use';

// Gateway (Device & Message Routing)
export {
  GatewayAPI,
  type DeviceStatus,
  type GatewayDevice,
  type GatewayChannel,
  type RoutingRule as GatewayRoutingRule,
  type RoutingStats,
  type ListDevicesOptions,
  type RegisterDeviceOptions,
  type RouteMessageOptions,
} from './gateway';

// Inbox Command (Email Prioritization)
export {
  InboxCommandAPI,
  type Priority as InboxPriority,
  type Action as InboxAction,
  type BulkFilter,
  type ForceTier,
  type InboxEmail,
  type InboxStats as InboxCommandStats,
  type SenderProfile,
  type DailyDigest,
  type GetInboxOptions,
  type QuickActionOptions,
  type BulkActionOptions,
  type ReprioritizeOptions,
} from './inbox-command';

// Knowledge Chat (Chat + Knowledge Bridge)
export {
  KnowledgeChatAPI,
  type SearchScope as KnowledgeChatSearchScope,
  type SearchStrategy as KnowledgeChatSearchStrategy,
  type ChatMessage as KnowledgeChatMessage,
  type KnowledgeSearchResult as KnowledgeChatSearchResult,
  type KnowledgeContextItem as KnowledgeChatContextItem,
  type ChannelKnowledgeSummary,
  type KnowledgeSearchOptions as KnowledgeChatSearchOptions,
  type KnowledgeInjectOptions,
  type KnowledgeStoreOptions,
  type ChannelSummaryOptions,
} from './knowledge-chat';

// ML (Machine Learning)
export {
  MLAPI,
  type ExportFormat as MLExportFormat,
  type QualityScore,
  type RoutingResult,
  type ConsensusPrediction,
  type EmbeddingResult,
  type SearchResult as MLSearchResult,
  type MLModel,
  type MLStats,
  type TrainingDebate,
  type RouteOptions,
  type ScoreOptions,
  type ScoreBatchOptions,
  type PredictConsensusOptions,
  type EmbedOptions,
  type SearchOptions as MLSearchOptions,
  type ExportTrainingOptions,
} from './ml';

// Orchestration (Multi-Agent Deliberation)
export {
  OrchestrationAPI,
  type TeamStrategy,
  type OutputFormat as OrchestrationOutputFormat,
  type DeliberationStatus as OrchestrationDeliberationStatus,
  type KnowledgeSource,
  type OutputChannel,
  type DeliberationTemplate,
  type DeliberationResult,
  type DeliberateOptions,
} from './orchestration';

// Partner (Partner Management)
export {
  PartnerAPI,
  type PartnerProfile,
  type PartnerApiKey,
  type PartnerUsage,
  type PartnerLimits,
  type RegisterPartnerOptions,
  type CreateApiKeyOptions,
} from './partner';

// SCIM 2.0 (Identity Provisioning)
export {
  SCIMAPI,
  type ScimUserName,
  type ScimEmail,
  type ScimPhoneNumber,
  type ScimUser,
  type ScimGroupMember,
  type ScimGroup,
  type ScimListResponse,
  type ScimPatchOp,
  type ScimListOptions,
} from './scim';

// Workflow Templates (Pre-built Automation)
export {
  WorkflowTemplatesAPI,
  type WorkflowTemplate as WorkflowTemplateEntry,
  type WorkflowTemplatePackage,
  type WorkflowTemplateRunResult,
  type ListWorkflowTemplatesParams,
  type RunWorkflowTemplateParams,
} from './workflow-templates';

// Media (Audio & Podcast)
export {
  MediaAPI,
  type AudioFile,
  type PodcastEpisode as MediaPodcastEpisode,
  type PodcastFeed as MediaPodcastFeed,
} from './media';

// Auditing (Deep Audit & Red Team)
export {
  AuditingAPI,
  type CapabilityProbeRequest as AuditCapabilityProbeRequest,
  type CapabilityProbeResult,
  type DeepAuditRequest,
  type DeepAuditResult,
  type RedTeamRequest,
  type RedTeamResult,
  type AttackType,
} from './auditing';

// Social (Social Media Publishing)
export {
  SocialAPI,
  type YouTubeAuthResponse,
  type YouTubeCallbackParams,
  type YouTubeStatus,
  type PublishRequest,
  type PublishResult,
} from './social';

// Security (Admin Security Management)
export {
  SecurityAPI,
  type SecurityLevel,
  type KeyStatus,
  type CheckStatus,
  type ThreatStatus,
  type SecurityStatus as SecurityAdminStatus,
  type SecurityHealthCheck,
  type SecurityKey as SecurityAdminKey,
  type RotateKeyRequest,
  type RotateKeyResult,
  type CreateKeyRequest,
  type RevokeKeyRequest,
  type SecurityScan,
  type SecurityFinding,
  type AuditLogEntry as SecurityAuditLogEntry,
  type ComplianceStatus as SecurityComplianceStatus,
  type SecurityThreat,
} from './security';

// Reviews (Decision Reviews)
export {
  ReviewsAPI,
  type Review,
} from './reviews';

export {
  ReviewQueueAPI,
  type ReviewQueuePR,
  type ReviewQueueStats,
  type BriefVerdict,
} from './review-queue';

// Checkpoints (Debate Pause/Resume)
export {
  CheckpointsAPI,
  type Checkpoint,
  type ResumableDebate,
  type InterventionRequest,
  type KMCheckpoint,
  type CheckpointComparison,
} from './checkpoints';

// Uncertainty (Uncertainty Estimation)
export {
  UncertaintyAPI,
  type UncertaintyEstimateRequest,
  type UncertaintyEstimate,
  type DebateUncertaintyMetrics,
  type AgentCalibrationProfile,
  type FollowUpRequest,
  type FollowUpSuggestion,
} from './uncertainty';

// Audio (Audio Files & Podcasts)
export {
  AudioAPI,
  type AudioFileInfo,
  type PodcastEpisode as AudioPodcastEpisode,
} from './audio';

// Hybrid Debates (External + Internal Agent Coordination)
export {
  HybridDebatesAPI,
  type HybridDebateStatus,
  type HybridDebateConfig,
  type HybridDebateResult,
  type HybridDebateListResponse,
  type CreateHybridDebateRequest,
  type ListHybridDebatesOptions,
} from './hybrid-debates';

// External Agents (OpenHands, AutoGPT, CrewAI Integration)
export {
  ExternalAgentsAPI,
  type ExternalAdapter,
  type AdapterListResponse,
  type AdapterHealth,
  type HealthResponse as ExternalAgentsHealthResponse,
  type TaskSubmitOptions,
  type TaskSubmitResponse,
  type TaskInfo,
  type CancelResponse as ExternalAgentsCancelResponse,
} from './external-agents';

// New namespaces

// Canvas (Live Collaboration)
export {
  CanvasNamespace,
  type Canvas,
  type CanvasNode,
  type CanvasEdge,
  type CreateCanvasRequest,
  type CanvasActionRequest,
} from './canvas';

// Ideas (Idea Canvas - Stage 1)
export {
  IdeasNamespace,
  type IdeaCanvas,
  type IdeaNode,
  type IdeaEdge,
  type PromotionResult,
} from './ideas';

// Costs (Cost Tracking)
export {
  CostsNamespace,
  type CostSummary as CostsNamespaceSummary,
  type BudgetAlert as CostsNamespaceBudgetAlert,
  type CostRecommendation as CostsNamespaceRecommendation,
  type CostTimelineEntry,
} from './costs';

// Voice (TTS Integration)
export {
  VoiceNamespace,
  type VoiceSession,
  type SynthesizeRequest,
  type SynthesizeResult,
  type VoiceConfig,
} from './voice';

// Shared Inbox (Team Inbox)
export {
  SharedInboxNamespace,
  type SharedInboxMessageStatus,
  type SharedInboxMessage as SharedInboxNamespaceMessage,
  type SharedInbox as SharedInboxNamespaceInbox,
  type RoutingRule as SharedInboxRoutingRule,
  type CreateSharedInboxRequest,
} from './shared-inbox';

// GitHub (Repository Integration)
export {
  GitHubNamespace,
  type PullRequest,
  type PRReviewResult,
  type PRFinding,
  type TriggerReviewRequest,
} from './github';

// Autonomous (Self-Learning)
export {
  AutonomousNamespace,
  type ApprovalRequest as AutonomousApprovalRequest,
  type Trigger as AutonomousTrigger,
  type AutonomousAlert,
  type AutonomousMetrics,
} from './autonomous';

// Approvals (Human-in-the-Loop)
export {
  ApprovalsAPI,
  type ApprovalRequest,
} from './approvals';

// Audit Trail (Compliance)
export {
  AuditTrailAPI,
  type AuditTrailSummary,
  type AuditTrailVerification,
  type AuditTrailExportFormat,
} from './audit-trail';

// OpenClaw (Legal Analysis)
export {
  OpenClawNamespace,
  type SessionStatus as OpenClawSessionStatus,
  type ActionStatus as OpenClawActionStatus,
  type OpenClawSession,
  type OpenClawAction,
  type OpenClawCredential,
  type CreateSessionRequest,
} from './openclaw';

// Blockchain (ERC-8004)
export {
  BlockchainNamespace,
  type BlockchainSyncRequest,
} from './blockchain';

// Pipeline (Idea-to-Execution)
export {
  PipelineNamespace,
  type PipelineRunRequest,
  type PipelineRunResponse,
  type PipelineStageStatus,
  type PipelineStatusResponse,
  type PipelineGraphResponse,
  type PipelineReceiptResponse,
} from './pipeline';
export { PipelineTransitionsNamespace } from './pipeline-transitions';

// DAG Operations (Pipeline graph-level automation)
export {
  DagOperationsNamespace,
  type DagOperationResult,
  type DagOperationResponse,
  type DagGraphResponse,
  type DebateNodeOptions,
  type AssignAgentsOptions,
  type FindPrecedentsOptions,
  type ClusterIdeasOptions,
  type AutoFlowOptions,
} from './dag-operations';

// DevOps (Incident Management)
export {
  DevOpsNamespace,
  type Incident,
  type OnCallEntry,
  type DevOpsService,
  type CreateIncidentRequest,
  type DevOpsStatus,
} from './devops';

// Search (Cross-Platform Search)
export {
  SearchNamespace,
  type SearchResult as SearchNamespaceResult,
  type SearchResponse,
  type SearchFacet,
  type SearchOptions as SearchNamespaceOptions,
} from './search';

// Status (Platform Status Page)
export {
  StatusNamespace,
  type PlatformStatus,
  type ServiceComponent,
  type StatusIncident,
  type MaintenanceWindow,
  type StatusSummary,
} from './status';

// Reconciliation (Financial Reconciliation)
export {
  ReconciliationNamespace,
  type ReconciliationStatus,
  type ReconciliationJob,
  type Discrepancy,
  type CreateReconciliationRequest,
} from './reconciliation';

// Workspace Settings (Configuration)
export {
  WorkspaceSettingsNamespace,
  type WorkspaceSettingsData,
  type IntegrationConfig as WorkspaceIntegrationConfig,
  type NotificationPreferences,
  type UpdateSettingsRequest,
} from './workspace-settings';

// Quotas (Resource Limits)
export {
  QuotasNamespace,
  type QuotaResource,
  type Quota,
  type QuotaPolicy,
  type QuotaUsageEntry,
} from './quotas';

// Services (Service Discovery)
export {
  ServicesNamespace,
  type ServiceHealthStatus,
  type Service as DiscoveredService,
} from './services';

// E-commerce (Product & Order Management)
export {
  EcommerceNamespace,
  type Product,
  type Order,
  type OrderItem,
  type EcommerceAnalytics,
} from './ecommerce';

// CRM (Customer Relationship Management)
export {
  CRMNamespace,
  type Contact,
  type Deal,
  type Activity as CRMActivity,
  type CreateContactRequest,
} from './crm';

// Support (Customer Support)
export {
  SupportNamespace,
  type TicketPriority,
  type TicketStatus,
  type Ticket,
  type TicketReply,
  type CreateTicketRequest,
  type SupportMetrics,
} from './support';

// Selection (Agent Selection)
export {
  SelectionNamespace,
  type SelectionScore,
  type SelectedTeamMember,
  type SelectionHistoryItem,
  type SelectTeamRequest as SelectionTeamRequest,
  type SelectTeamResult as SelectionTeamResult,
} from './selection';

// Features (Feature Flags)
export { FeaturesAPI } from './features';

// Self-Improve (Autonomous Improvement Runs)
export {
  SelfImproveAPI,
  type SelfImproveRunStatus,
  type SelfImproveMode,
  type SelfImproveRun,
  type Worktree,
  type StartRunRequest,
} from './self-improve';

// Index (Vector Indexing & Semantic Search)
export {
  IndexAPI,
  type IndexStatus as VectorIndexStatus,
  type EmbedOptions as IndexEmbedOptions,
  type EmbedBatchOptions as IndexEmbedBatchOptions,
  type SearchOptions as IndexSearchOptions,
  type SearchIndexOptions,
  type CreateIndexOptions,
} from './vector-index';

// Benchmarks
export { BenchmarksAPI } from './benchmarks';

// Breakpoints
export { BreakpointsAPI } from './breakpoints';

// Channels
export { ChannelsAPI } from './channels';

// Context
export { ContextAPI } from './context';

// Feature Flags
export { FeatureFlagsAPI } from './feature-flags';

// n8n Integration
export { N8nAPI } from './n8n';

// Outcomes
export { OutcomesAPI } from './outcomes';

// Plans
export { PlansAPI } from './plans';

// Playbooks
export { PlaybooksAPI } from './playbooks';

// Readiness
export { ReadinessAPI } from './readiness';

// Tasks
export { TasksAPI } from './tasks';

// Settlements
export { SettlementsAPI } from './settlements';

// Templates
export { TemplatesAPI } from './templates';

// Users
export { UsersAPI } from './users';

// Actions (Action Canvas - Pipeline Stage 3)
export {
  ActionsNamespace,
  type ActionNode,
  type ActionEdge,
  type ActionCanvas,
  type AdvanceResult,
} from './actions';

// Graph Debates
export { GraphDebatesAPI } from './graph-debates';

// Matrix Debates
export { MatrixDebatesAPI } from './matrix-debates';

// Orchestration Canvas (Pipeline Stage 4)
export {
  OrchestrationCanvasNamespace,
  type OrchestrationNode,
  type OrchestrationEdge,
  type OrchestrationCanvas,
  type ExecutionResult as OrchestrationExecutionResult,
} from './orchestration_canvas';
