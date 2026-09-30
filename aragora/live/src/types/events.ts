export type StreamEventType =
  // Debate events
  | 'debate_start'
  | 'round_start'
  | 'agent_message'
  | 'critique'
  | 'vote'
  | 'consensus'
  | 'synthesis'
  | 'verdict'
  | 'grounded_verdict'
  | 'debate_end'
  // Nomic loop events
  | 'cycle_start'
  | 'cycle_end'
  | 'phase_start'
  | 'phase_end'
  | 'phase_timeout'
  | 'task_start'
  | 'task_complete'
  | 'task_retry'
  | 'verification_start'
  | 'verification_result'
  | 'commit'
  | 'backup_created'
  | 'backup_restored'
  | 'error'
  | 'log_message'
  | 'sync'
  // Multi-loop events
  | 'loop_register'
  | 'loop_unregister'
  | 'loop_list'
  // Audience participation events
  | 'user_vote'
  | 'user_suggestion'
  | 'audience_summary'
  | 'audience_metrics'
  | 'audience_drain'
  | 'ack'
  // Ranking/insight events
  | 'match_recorded'
  | 'leaderboard_update'
  | 'moment_detected'
  | 'agent_elo_updated'
  | 'flip_detected'
  | 'memory_recall'
  | 'insight_extracted'
  // Claim verification events
  | 'claim_verification_result'
  | 'formal_verification_result'
  // Memory tier events
  | 'memory_tier_promotion'
  | 'memory_tier_demotion'
  // Trickster/hollow consensus events
  | 'hollow_consensus'
  | 'trickster_intervention'
  // Rhetorical analysis
  | 'rhetorical_observation'
  // Crux detection (key disagreements)
  | 'crux_detected'
  // User intervention events (mid-debate controls)
  | 'intervention_pause'
  | 'intervention_resume'
  | 'intervention_inject'
  | 'intervention_weight'
  | 'intervention_threshold'
  // Token streaming events
  | 'token_start'
  | 'token_delta'
  | 'token_end'
  // Reasoning visibility events (real-time agent reasoning)
  | 'agent_thinking'
  | 'agent_reasoning'
  | 'agent_evidence'
  | 'agent_confidence'
  // Mood/sentiment events (Real-Time Debate Drama)
  | 'mood_detected'
  | 'mood_shift'
  | 'debate_energy'
  // Capability probe events (Adversarial Testing)
  | 'probe_start'
  | 'probe_result'
  | 'probe_complete'
  // Deep Audit events (Intensive Multi-Round Analysis)
  | 'audit_start'
  | 'audit_round'
  | 'audit_finding'
  | 'audit_cross_exam'
  | 'audit_verdict'
  // Feature integration events (real-time panel updates)
  | 'trait_emerged'
  | 'risk_warning'
  | 'evidence_found'
  | 'calibration_update'
  | 'genesis_evolution'
  | 'training_data_exported'
  // Human intervention breakpoint events
  | 'breakpoint'
  | 'breakpoint_resolved'
  // Uncertainty quantification events
  | 'uncertainty_analysis'
  // Graph debate events
  | 'debate_branch'
  | 'debate_merge'
  | 'graph_node_added'
  | 'graph_branch_created'
  | 'graph_branch_merged'
  // Matrix debate events
  | 'scenario_complete'
  | 'matrix_complete'
  // Progress/heartbeat events (for detecting stalls)
  | 'heartbeat'
  | 'agent_error'
  | 'phase_progress'
  // Quick preview events (shown in first 5 seconds)
  | 'quick_classification'
  | 'agent_preview'
  | 'context_preview'
  // Gauntlet events (Adversarial Validation)
  | 'gauntlet_start'
  | 'gauntlet_phase'
  | 'gauntlet_agent_active'
  | 'gauntlet_attack'
  | 'gauntlet_finding'
  | 'gauntlet_probe'
  | 'gauntlet_verification'
  | 'gauntlet_risk'
  | 'gauntlet_progress'
  | 'gauntlet_verdict'
  | 'gauntlet_complete'
  // Workflow Builder events
  | 'workflow_created'
  | 'workflow_updated'
  | 'workflow_deleted'
  | 'workflow_start'
  | 'workflow_step_start'
  | 'workflow_step_progress'
  | 'workflow_step_complete'
  | 'workflow_step_failed'
  | 'workflow_step_skipped'
  | 'workflow_transition'
  | 'workflow_checkpoint'
  | 'workflow_resumed'
  | 'workflow_human_approval_required'
  | 'workflow_human_approval_received'
  | 'workflow_human_approval_timeout'
  | 'workflow_debate_start'
  | 'workflow_debate_round'
  | 'workflow_debate_complete'
  | 'workflow_memory_read'
  | 'workflow_memory_write'
  | 'workflow_complete'
  | 'workflow_failed'
  | 'workflow_terminated'
  | 'workflow_metrics';

// Base interface for all stream events
interface StreamEventBase {
  timestamp: number;
  round?: number;
  agent?: string;
  seq?: number; // Global sequence number for ordering
  agent_seq?: number; // Per-agent sequence number for token stream ordering
}

// Specific event data types for type-safe access
export interface AgentMessageData {
  agent: string;
  content: string;
  role?: string;
  cognitive_role?: string;
  confidence?: number;
  citations?: string[];
  // Reasoning visibility fields
  confidence_score?: number;
  reasoning_phase?: string;
  thinking?: string;
}

export interface DebateStartData {
  debate_id: string;
  task: string;
  agents: string[];
  rounds: number;
  filtered?: boolean;
  missing_agents?: string[];
  requested_agents?: string[];
}

export interface RoundStartData {
  round: number;
  total_rounds: number;
}

export interface VoteData {
  agent: string;
  choice: string;
  vote?: string; // Alternative field name for choice
  confidence: number;
  reasoning?: string;
}

export interface ConsensusData {
  reached: boolean;
  topic?: string;
  confidence?: number;
  supporting_agents?: string[];
  answer?: string;
  status?: string;
  agent_failures?: Record<string, AgentFailureRecord[]>;
}

export interface VerdictData {
  winner?: string;
  reasoning: string;
  scores?: Record<string, number>;
  citations?: string[];
}

export interface AgentFailureRecord {
  phase?: string;
  error_type?: string;
  message?: string;
  provider?: string;
  timestamp?: number;
}

export interface AgentErrorData {
  error_type?: string;
  message?: string;
  recoverable?: boolean;
  phase?: string;
}
export interface TokenDeltaData {
  agent: string;
  delta: string;
  accumulated?: string;
}

// Reasoning visibility event data types
export interface AgentThinkingData {
  agent: string;
  thinking: string;
  step?: number;
  phase?: string;
}

export interface AgentEvidenceData {
  agent: string;
  sources: Array<{ title: string; url?: string; relevance?: number }>;
  query?: string;
}

export interface AgentReasoningData {
  agent: string;
  phase?: string;
  reasoning_phase?: string;
  thinking?: string;
}

export interface AgentConfidenceData {
  agent: string;
  confidence: number;
  previous?: number;
  reason?: string;
}

export interface MoodData {
  agent: string;
  mood: string;
  confidence: number;
  indicators?: string[];
}

export interface MemoryRecallData {
  query: string;
  hits: Array<{ topic: string; similarity: number }>;
  count: number;
}

export interface FlipDetectedData {
  agent_name: string;
  flip_type: 'contradiction' | 'retraction' | 'qualification' | 'refinement';
  original_claim: string;
  new_claim: string;
  original_confidence?: number;
  new_confidence?: number;
  similarity_score?: number;
  domain?: string;
  detected_at?: string;
}

export interface HollowConsensusData {
  details: string;
  metric: number;
  agent: string;
  round?: number;
}

export interface TricksterInterventionData {
  intervention_type: string;
  targets: string[];
  challenge: string;
  round_num: number;
  priority?: number;
}

export interface RhetoricalObservationData {
  agent: string;
  patterns: string[];
  round: number;
  analysis?: string;
}

export interface UncertaintyCrux {
  claim: string;
  uncertainty: number;
  supporting_agents: string[];
  opposing_agents: string[];
  topic?: string;
}

export interface UncertaintyAnalysisData {
  collective_confidence: number;
  confidence_interval: [number, number];
  disagreement_type: 'consensus' | 'mild' | 'moderate' | 'severe' | 'polarized';
  cruxes: UncertaintyCrux[];
  calibration_quality: number;
}

export interface EvidenceSnippet {
  id: string;
  source: string;
  title: string;
  snippet: string;
  url: string;
  reliability_score: number;
  freshness_score: number;
}

export interface EvidenceFoundData {
  keywords: string[];
  count: number;
  snippets: EvidenceSnippet[];
}

// Quick preview event data types (shown in first 5 seconds)
export interface QuickClassificationData {
  question_type: 'factual' | 'ethical' | 'technical' | 'creative' | 'policy' | 'comparative';
  domain: 'science' | 'technology' | 'philosophy' | 'politics' | 'society' | 'economics' | 'other';
  complexity: 'simple' | 'moderate' | 'complex';
  key_aspects: string[];
  suggested_approach: string;
}

export interface AgentPreviewItem {
  name: string;
  role: string;
  stance: 'agree' | 'disagree' | 'neutral';
  description: string;
  strengths: string[];
}

export interface AgentPreviewData {
  agents: AgentPreviewItem[];
  topology: string;
}

export interface TrendingTopicPreview {
  topic: string;
  platform: string;
  volume: number;
}

export interface ContextPreviewData {
  trending_topics: TrendingTopicPreview[];
  research_status: string;
  evidence_sources: string[];
}

// Discriminated union of specific event types
export type TypedStreamEvent =
  | (StreamEventBase & { type: 'agent_message'; data: AgentMessageData })
  | (StreamEventBase & { type: 'debate_start'; data: DebateStartData })
  | (StreamEventBase & { type: 'round_start'; data: RoundStartData })
  | (StreamEventBase & { type: 'vote'; data: VoteData })
  | (StreamEventBase & { type: 'consensus'; data: ConsensusData })
  | (StreamEventBase & { type: 'agent_error'; data: AgentErrorData })
  | (StreamEventBase & { type: 'verdict' | 'grounded_verdict'; data: VerdictData })
  | (StreamEventBase & { type: 'token_delta'; data: TokenDeltaData })
  | (StreamEventBase & { type: 'mood_detected' | 'mood_shift'; data: MoodData })
  | (StreamEventBase & { type: 'memory_recall'; data: MemoryRecallData })
  | (StreamEventBase & { type: 'flip_detected'; data: FlipDetectedData })
  | (StreamEventBase & { type: 'audience_summary'; data: AudienceSummaryData })
  | (StreamEventBase & { type: 'audience_metrics'; data: AudienceMetricsData })
  | (StreamEventBase & { type: 'audit_finding'; data: AuditFinding })
  | (StreamEventBase & { type: 'audit_round'; data: AuditRoundData })
  | (StreamEventBase & { type: 'audit_verdict'; data: AuditVerdictData })
  | (StreamEventBase & { type: 'hollow_consensus'; data: HollowConsensusData })
  | (StreamEventBase & { type: 'trickster_intervention'; data: TricksterInterventionData })
  | (StreamEventBase & { type: 'rhetorical_observation'; data: RhetoricalObservationData })
  | (StreamEventBase & { type: 'uncertainty_analysis'; data: UncertaintyAnalysisData })
  | (StreamEventBase & { type: 'evidence_found'; data: EvidenceFoundData })
  | (StreamEventBase & { type: 'quick_classification'; data: QuickClassificationData })
  | (StreamEventBase & { type: 'agent_preview'; data: AgentPreviewData })
  | (StreamEventBase & { type: 'context_preview'; data: ContextPreviewData })
  | (StreamEventBase & { type: 'agent_thinking'; data: AgentThinkingData })
  | (StreamEventBase & { type: 'agent_reasoning'; data: AgentReasoningData })
  | (StreamEventBase & { type: 'agent_evidence'; data: AgentEvidenceData })
  | (StreamEventBase & { type: 'agent_confidence'; data: AgentConfidenceData });

// Generic event type for events not yet specifically typed
export interface GenericStreamEvent extends StreamEventBase {
  type: StreamEventType;
  data: Record<string, unknown>;
}

// Union type that accepts both typed and generic events
// Use TypedStreamEvent when you need type safety, StreamEvent for general use
export type StreamEvent = TypedStreamEvent | GenericStreamEvent;

// Type guard helpers
export function isAgentMessage(
  event: StreamEvent,
): event is StreamEventBase & { type: 'agent_message'; data: AgentMessageData } {
  return event.type === 'agent_message';
}

export function isMemoryRecall(
  event: StreamEvent,
): event is StreamEventBase & { type: 'memory_recall'; data: MemoryRecallData } {
  return event.type === 'memory_recall';
}

export function isFlipDetected(
  event: StreamEvent,
): event is StreamEventBase & { type: 'flip_detected'; data: FlipDetectedData } {
  return event.type === 'flip_detected';
}

export function isAudienceSummary(
  event: StreamEvent,
): event is StreamEventBase & { type: 'audience_summary'; data: AudienceSummaryData } {
  return event.type === 'audience_summary';
}

export function isAudienceMetrics(
  event: StreamEvent,
): event is StreamEventBase & { type: 'audience_metrics'; data: AudienceMetricsData } {
  return event.type === 'audience_metrics';
}

export function isUncertaintyAnalysis(
  event: StreamEvent,
): event is StreamEventBase & { type: 'uncertainty_analysis'; data: UncertaintyAnalysisData } {
  return event.type === 'uncertainty_analysis';
}

export function isEvidenceFound(
  event: StreamEvent,
): event is StreamEventBase & { type: 'evidence_found'; data: EvidenceFoundData } {
  return event.type === 'evidence_found';
}

export function isQuickClassification(
  event: StreamEvent,
): event is StreamEventBase & { type: 'quick_classification'; data: QuickClassificationData } {
  return event.type === 'quick_classification';
}

export function isAgentPreview(
  event: StreamEvent,
): event is StreamEventBase & { type: 'agent_preview'; data: AgentPreviewData } {
  return event.type === 'agent_preview';
}

export function isContextPreview(
  event: StreamEvent,
): event is StreamEventBase & { type: 'context_preview'; data: ContextPreviewData } {
  return event.type === 'context_preview';
}

export interface NomicState {
  phase?: string;
  stage?: string;
  cycle?: number;
  total_tasks?: number;
  completed_tasks?: number;
  last_task?: string;
  last_success?: boolean;
  saved_at?: string;
  status?: string;
  message?: string;
}

export interface AgentMessage {
  id: string;
  agent: string;
  content: string;
  role: string;
  round: number;
  timestamp: number;
  isExpanded: boolean;
}

export interface CritiqueMessage {
  id: string;
  agent: string;
  target: string;
  issues: string[];
  severity: number;
  round: number;
  timestamp: number;
}

export type Phase = 'idle' | 'debate' | 'design' | 'implement' | 'verify' | 'commit';

export interface PhaseStatus {
  phase: Phase;
  started?: number;
  ended?: number;
  success?: boolean;
  details?: Record<string, unknown>;
}

// Multi-loop support
export interface LoopInstance {
  loop_id: string;
  name: string;
  started_at: number;
  cycle: number;
  phase: string;
  path: string;
}

export interface LoopListData {
  loops: LoopInstance[];
  count: number;
}

// Audience summary data from clustered suggestions
export interface AudienceSummaryData {
  clusters: Array<{ representative: string; count: number }>;
  total: number;
  mode: 'summary' | 'inject';
}

// Conviction-weighted voting data
export interface ConvictionHistogram {
  [intensity: number]: number; // intensity (1-10) -> count
}

export interface AudienceMetricsData {
  votes: Record<string, number>; // choice -> raw count
  weighted_votes?: Record<string, number>; // choice -> conviction-weighted count
  suggestions: number;
  total: number;
  histograms?: Record<string, ConvictionHistogram>; // choice -> intensity histogram
  conviction_distribution?: ConvictionHistogram; // global intensity distribution
}

// Deep Audit event data types
export interface AuditFinding {
  category: 'unanimous' | 'split' | 'risk' | 'insight';
  summary: string;
  details: string;
  agents_agree: string[];
  agents_disagree: string[];
  confidence: number;
  citations: string[];
  severity: number;
}

export interface AuditRoundData {
  round: number;
  name: string;
  cognitive_role: string;
  messages: Array<{ agent: string; content: string; confidence?: number }>;
  duration_ms: number;
}

export interface AuditVerdictData {
  audit_id: string;
  task: string;
  recommendation: string;
  confidence: number;
  unanimous_issues: string[];
  split_opinions: string[];
  risk_areas: string[];
  findings: AuditFinding[];
  citations: string[];
  cross_examination_notes: string;
  rounds_completed: number;
  total_duration_ms: number;
  agents: string[];
  elo_adjustments: Record<string, number>;
}
