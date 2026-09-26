/**
 * Aragora React Hooks
 *
 * Central export for all Aragora React hooks.
 * Import from '@/hooks' instead of individual files.
 *
 * @example
 * ```typescript
 * import {
 *   useAragoraClient,
 *   useDebateWebSocket,
 *   useAuth,
 *   useWorkspaces
 * } from '@/hooks';
 *
 * function MyComponent() {
 *   const client = useAragoraClient();
 *   const { debates } = await client.debates.list();
 * }
 * ```
 */

// =============================================================================
// Core Client & Auth
// =============================================================================

export { useAragoraClient, useClientCleanup, useClientAuth } from './useAragoraClient';
export { useAuth } from '@/context/AuthContext';
export { useAuthenticatedFetch } from './useAuthenticatedFetch';
export { useSession } from './useSession';

// =============================================================================
// API & Data Fetching
// =============================================================================

export { useApi } from './useApi';
export { useFetch } from './useFetch';
export { useSWRFetch } from './useSWRFetch';
export { useAsyncData } from './useAsyncData';

// =============================================================================
// Debate Hooks
// =============================================================================

export { useDebateWebSocket } from './debate-websocket/useDebateWebSocket';
export { useDebateFork } from './useDebateFork';
export { useBatchDebate } from './useBatchDebate';
export { useGraphDebateWebSocket } from './useGraphDebateWebSocket';
export { useDebateWebSocketStore } from './useDebateWebSocketStore';
export { useDebateInterventions } from './useDebateInterventions';
export type {
  InterventionEntry,
  InterventionLog,
  InterventionResult,
} from './useDebateInterventions';

// Re-export debate WebSocket types
export type {
  TranscriptMessage,
  StreamingMessage,
  DebateConnectionStatus,
  UseDebateWebSocketOptions,
  UseDebateWebSocketReturn,
} from './debate-websocket/types';

// =============================================================================
// Workspace & Organization
// =============================================================================

export { useWorkspaces } from './useWorkspaces';
export { useWorkspaceInvites } from './useWorkspaceInvites';

// =============================================================================
// Knowledge & Evidence
// =============================================================================

export { useKnowledgeQuery } from './useKnowledgeQuery';
export { useEvidence } from './useEvidence';
export { useGlobalKnowledge } from './useGlobalKnowledge';

// =============================================================================
// Explainability
// =============================================================================

export { useExplanation } from './useExplanation';
export type {
  ExplanationData,
  EvidenceLink as ExplanationEvidenceLink,
  VotePivot,
  BeliefChange,
  ConfidenceAttribution,
  Counterfactual,
} from './useExplanation';

// =============================================================================
// Control Plane & Policies
// =============================================================================

export { useControlPlane } from './useControlPlane';
export { useControlPlaneWebSocket } from './useControlPlaneWebSocket';
export { usePolicies } from './usePolicies';

// =============================================================================
// Workflow & Automation
// =============================================================================

export { useWorkflows } from './useWorkflows';
export type {
  Workflow,
  WorkflowStep,
  WorkflowVersion,
  WorkflowTemplate,
  SimulationResult,
  ApprovalRequest as WorkflowApprovalRequest,
} from './useWorkflows';
export { useWorkflowBuilder } from './useWorkflowBuilder';
export { useWorkflowExecution } from './useWorkflowExecution';
export { useWorkflowWebSocket } from './useWorkflowWebSocket';
export { usePipeline } from './usePipeline';
export { usePipelineCanvas } from './usePipelineCanvas';
export { usePipelineWebSocket } from './usePipelineWebSocket';
export { useUnifiedDAG } from './useUnifiedDAG';
export type { DAGNodeData, DAGOperationResult, DAGStage } from './useUnifiedDAG';
export { useFractalNavigation } from './useFractalNavigation';
export type { NavigationLevel, FractalNavigationResult } from './useFractalNavigation';
export { usePlaybooks } from './usePlaybooks';

// =============================================================================
// Monitoring & Analytics
// =============================================================================

export { useCosts } from './useCosts';
export { useUsageDashboard, useUsageTrend, useCostBreakdown } from './useUsageDashboard';
export { useQueueMonitoring } from './useQueueMonitoring';

// Spend Analytics Dashboard
export {
  useSpendAnalytics,
  useSpendTrend,
  useSpendForecast,
  useSpendAnomalies,
  useSpendDashboardSummary,
  useSpendDashboardTrends,
  useSpendDashboardByAgent,
  useSpendDashboardByDecision,
  useSpendDashboardBudget,
} from './useSpendAnalytics';
export type {
  SpendDashboardSummary,
  SpendDashboardTrends,
  SpendDashboardByAgent,
  SpendDashboardByDecision,
  SpendDashboardBudget,
  AgentSpendEntry,
  DecisionSpendEntry,
  SpendPeriod,
  SpendAnomaly,
} from './useSpendAnalytics';

// =============================================================================
// ELO Analytics
// =============================================================================

export {
  useEloTrends,
  useAgentEloDetail,
  useRankingStats,
  useDomainLeaderboard,
} from './useEloAnalytics';
export type {
  EloHistoryPoint,
  AgentEloDetail,
  AgentTrendData,
  DomainLeaderboardEntry,
} from './useEloAnalytics';

// =============================================================================
// System Health & Resilience
// =============================================================================

export {
  useSystemHealth,
  useCircuitBreakers,
  useSLOStatus,
  useAgentPoolHealth,
  useBudgetStatus,
} from './useSystemHealth';
export type { CircuitBreakerInfo, SLOInfo, SystemHealthOverview } from './useSystemHealth';

// =============================================================================
// Integrations & Connectors
// =============================================================================

export { useConnectorWebSocket } from './useConnectorWebSocket';
export { useBroadcast } from './useBroadcast';
export { useAgentRouting } from './useAgentRouting';

// =============================================================================
// Spectate (Real-Time Debate Observation)
// =============================================================================

export { useSpectate } from './useSpectate';
export type { SpectateEvent } from './useSpectate';

// =============================================================================
// Gauntlet & Testing
// =============================================================================

export { useGauntletWebSocket } from './useGauntletWebSocket';

// =============================================================================
// Nomic (Self-Improvement)
// =============================================================================

export { useNomicLoopWebSocket } from './useNomicLoopWebSocket';
export { useNomicStream } from './useNomicStream';

// =============================================================================
// Oracle
// =============================================================================

export { useOracleWebSocket } from './useOracleWebSocket';

// =============================================================================
// Debate Stream (Oracle streaming + TTS)
// =============================================================================

export { useDebateStream } from './useDebateStream';
export type {
  DebatePhase,
  TTSState,
  StreamMetrics,
  TTSControls as DebateStreamTTSControls,
  UseDebateStreamOptions,
  UseDebateStreamReturn,
} from './useDebateStream';

// =============================================================================
// Features & Capabilities
// =============================================================================

export { useFeatures } from './useFeatures';
export { useFineTuning } from './useFineTuning';

// =============================================================================
// UI & UX Helpers
// =============================================================================

export { useToast } from './useToast';
export { useFocusTrap } from './useFocusTrap';
export { useMediaQuery } from './useMediaQuery';
export { useSwipeGesture } from './useSwipeGesture';
export { useCommandPaletteSearch } from './useCommandPaletteSearch';
export { useDashboardPreferences } from './useDashboardPreferences';
export { useErrorHandler } from './useErrorHandler';
export { usePWA } from './usePWA';
export {
  useTimeout,
  useTimeoutEffect,
  useInterval,
  useIntervalEffect,
  useDebounce,
  useThrottle,
} from './useTimers';

// =============================================================================
// Data Management
// =============================================================================

export { useLocalHistory } from './useLocalHistory';
export { useSupabaseHistory } from './useSupabaseHistory';
export { useBlocklist } from './useBlocklist';
export { useDedup } from './useDedup';
export { usePruning } from './usePruning';
export { useVisibility } from './useVisibility';
export { useSharing } from './useSharing';
export { useFederation } from './useFederation';

// =============================================================================
// Pulse (Trending Topics)
// =============================================================================

export { usePulseScheduler } from './usePulseScheduler';

// =============================================================================
// Inbox
// =============================================================================

export { useInboxSync } from './useInboxSync';

// =============================================================================
// Base WebSocket
// =============================================================================

export { useWebSocketBase } from './useWebSocketBase';

// =============================================================================
// Self-Improve & Knowledge Flow
// =============================================================================

export {
  useMetaPlannerGoals,
  useExecutionTimeline,
  useLearningInsights,
  useMetricsComparison,
} from './useSelfImproveDetails';
export { useKnowledgeFlow } from './useKnowledgeFlow';
export { useUnifiedMemoryQuery } from './useUnifiedMemory';

// =============================================================================
// System Intelligence
// =============================================================================

export {
  useSystemIntelligence,
  useAgentPerformance,
  useInstitutionalMemory,
  useImprovementQueue,
} from './useSystemIntelligence';
export type {
  SystemOverview,
  AgentPerformanceEntry,
  InstitutionalMemory,
  ImprovementQueueItem,
  ImprovementQueueData,
} from './useSystemIntelligence';

// =============================================================================
// Mission Control & Agent Execution
// =============================================================================

export { useIsAdmin } from './usePermission';
export { useMissionControl } from './useMissionControl';
export { useBrainDumpPreview } from './useBrainDumpPreview';
export { useAgentExecution } from './useAgentExecution';
export { useIntelligence } from './useIntelligence';

// =============================================================================
// Dashboard
// =============================================================================

export {
  useDashboardOverview,
  useDashboardStats,
  useDashboardActivity,
  useDashboardInboxSummary,
  useDashboardStatCards,
  useDashboardQuickActions,
  useDashboardTeamPerformance,
  useDashboardUrgentItems,
  useDashboardPendingActions,
  useDashboardLabels,
  useOutcomeDashboard,
  useOutcomeQuality,
  useOutcomeAgents,
  useOutcomeHistory,
  useOutcomeCalibration,
  useUsageSummary,
  useUsageBreakdown,
  useBudgetStatusDashboard,
  useSpendSummary,
  useSpendByAgent,
  useSpendByDecision,
  useSpendBudgetForecast,
} from './useDashboard';
export type {
  DashboardOverview,
  DashboardStats,
  OutcomeQuality,
  OutcomeAgent,
  UsageSummary,
  SpendSummary,
} from './useDashboard';

// =============================================================================
// Belief Network
// =============================================================================

export { useBeliefNetwork } from './useBeliefNetwork';
export type {
  BeliefNode,
  BeliefLink,
  BeliefNetworkGraph,
  LoadBearingClaim,
  CruxAnalysis,
  ClaimSupport,
} from './useBeliefNetwork';

// =============================================================================
// Streaming & Dashboard Events
// =============================================================================

export { useStreamingAudio } from './useStreamingAudio';
export { useDashboardEvents } from './useDashboardEvents';

// =============================================================================
// Agent Evolution & Blockchain
// =============================================================================

export {
  useAgentEvolution,
  useAgentEloTrends,
  usePendingChanges,
  useAgentEvolutionDashboard,
} from './useAgentEvolution';
export type {
  EvolutionEvent,
  EvolutionTimeline,
  EloTrendPoint,
  AgentEloTrend,
  PendingChange,
} from './useAgentEvolution';
export {
  useBlockchainConfig,
  useBlockchainAgents,
  useBlockchainAgent,
  useBlockchainReputation,
  useBlockchainValidations,
  useBlockchainHealth,
} from './useBlockchain';
export type {
  ChainConfig,
  OnChainAgent,
  ReputationSummary,
  BlockchainHealth,
} from './useBlockchain';

// =============================================================================
// API Explorer & Command Center
// =============================================================================

export { useApiExplorer } from './useApiExplorer';
export type {
  OpenApiOperation,
  ParsedEndpoint,
  EndpointGroup,
  UseApiExplorerReturn,
} from './useApiExplorer';
export { useCommandCenter } from './useCommandCenter';
export type { InputMode, AutoFlowPhase, CommandStats } from './useCommandCenter';

// =============================================================================
// Compliance & Decision Analytics
// =============================================================================

export {
  useComplianceStatus,
  useRBACCoverage,
  useEncryptionStatus,
  useAuditTrail,
} from './useComplianceDashboard';
export type {
  RBACCoverage,
  EncryptionStatus,
  ComplianceFrameworks,
  AuditEntry,
} from './useComplianceDashboard';
export {
  useDecisionOverview,
  useDecisionTrends,
  useDecisionOutcomes,
  useAgentQuality,
  useDomainQuality,
  useDecisionAnalytics,
} from './useDecisionAnalytics';
export type {
  DecisionOverview,
  QualityTrendPoint as DecisionQualityTrend,
  AnalyticsPeriod,
} from './useDecisionAnalytics';
export { useDecisionIntegrity } from './useDecisionIntegrity';
export type { IntegrityMetrics, ConsensusMetrics, ReceiptStats } from './useDecisionIntegrity';

// =============================================================================
// Event Stream & Outcome Analytics
// =============================================================================

export { useEventStream } from './useEventStream';
export type {
  StreamEvent as EventStreamEvent,
  EventCategory,
  EventSeverity,
  EventFilters,
} from './useEventStream';
export {
  useOutcomeAnalytics,
  useOutcomeDashboard as useOutcomeAnalyticsDashboard,
  useQualityScore,
  useCalibrationCurve,
  useDecisionHistory,
} from './useOutcomeAnalytics';
export type {
  OutcomeDashboardData,
  OutcomePeriod,
  CalibrationData,
  DecisionHistoryEntry,
} from './useOutcomeAnalytics';
