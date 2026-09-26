// Auto-generated types from OpenAPI spec
// DO NOT EDIT - regenerate with: npm run generate:sdk

export type DebateStatus =
  | 'created'
  | 'starting'
  | 'pending'
  | 'running'
  | 'in_progress'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'paused'
  | 'active'
  | 'concluded'
  | 'archived';

export interface ConsensusResult {
  reached?: boolean;
  agreement?: number;
  confidence?: number;
  final_answer?: string;
  conclusion?: string;
  supporting_agents?: string[];
  dissenting_agents?: string[];
}

export interface DebateCreateRequest {
  /** The topic or question to debate */
  task?: string;
  /** Alias for task (legacy field) */
  question?: string;
  /** List of agent IDs to include */
  agents?: string[];
  /** Number of debate rounds */
  rounds?: number;
  /** Consensus detection method */
  consensus?: 'majority' | 'unanimous' | 'supermajority' | 'hybrid';
  /** Whether to auto-select optimal agents */
  auto_select?: boolean;
  /** Optional auto-select configuration */
  auto_select_config?: Record<string, unknown>;
  /** Use a trending topic instead of provided task */
  use_trending?: boolean;
  /** Trending category filter */
  trending_category?: string;
  /** Additional context for the debate */
  context?: string;
}

export interface DebateCreateResponse {
  success?: boolean;
  /** Unique identifier for the created debate */
  debate_id?: string;
  status?: DebateStatus;
  /** The debate topic */
  task?: string;
  error?: string;
}

export interface DebateSummary {
  debate_id?: string;
  id?: string;
  slug?: string;
  task?: string;
  status?: DebateStatus;
  consensus_reached?: boolean;
  confidence?: number;
  created_at?: string;
  rounds_used?: number;
  duration_seconds?: number;
  agents?: string[];
  view_count?: number;
  is_public?: boolean;
}

export interface Debate {
  debate_id?: string;
  id?: string;
  slug?: string;
  task?: string;
  context?: string;
  status?: DebateStatus;
  outcome?: string;
  final_answer?: string;
  consensus?: ConsensusResult;
  consensus_proof?: Record<string, unknown>;
  consensus_reached?: boolean;
  confidence?: number;
  rounds_used?: number;
  duration_seconds?: number;
  agents?: string[];
  rounds?: Round[];
  created_at?: string;
  completed_at?: string;
  metadata?: Record<string, unknown>;
}

export interface Round {
  round_number?: number;
  messages?: Message[];
  critiques?: Critique[];
}

export interface Message {
  agent_id?: string;
  agent?: string;
  content?: string;
  round?: number;
  timestamp?: string;
}

export interface Critique {
  author?: string;
  target?: string;
  content?: string;
  severity?: number;
}

export interface ImpasseAnalysis {
  impasse_detected?: boolean;
  indicators?: string[];
  circular_arguments?: Record<string, unknown>[];
  repetition_score?: number;
}

export interface ConvergenceStatus {
  converged?: boolean;
  similarity_score?: number;
  rounds_to_convergence?: number;
}

export interface Citations {
  citations?: { claim?: string; source?: string; confidence?: number }[];
  grounded_verdict?: Record<string, unknown>;
}

export interface LeaderboardEntry {
  rank?: number;
  agent?: string;
  elo?: number;
  wins?: number;
  losses?: number;
  win_rate?: number;
}

export interface Match {
  id?: string;
  debate_id?: string;
  winner?: string;
  loser?: string;
  elo_change?: number;
  timestamp?: string;
}

export interface AgentProfile {
  name?: string;
  elo?: number;
  rank?: number;
  wins?: number;
  losses?: number;
  win_rate?: number;
  specialties?: string[];
}

export interface MatchHistoryEntry {
  debate_id?: string;
  opponent?: string;
  result?: 'win' | 'loss' | 'draw';
  elo_change?: number;
  timestamp?: string;
}

export interface ConsistencyScore {
  agent?: string;
  consistency_score?: number;
  total_flips?: number;
  recent_flips?: number;
}

export interface RelationshipNetwork {
  agent?: string;
  rivals?: AgentRelation[];
  allies?: AgentRelation[];
}

export interface AgentRelation {
  agent?: string;
  score?: number;
  debates?: number;
}

export interface AgentComparison {
  agents?: AgentProfile[];
  head_to_head?: Record<string, Record<string, unknown>>;
}

export interface PositionFlip {
  agent?: string;
  topic?: string;
  old_position?: string;
  new_position?: string;
  debate_id?: string;
  timestamp?: string;
}

export interface DetailedHealth {
  status?: string;
  observers?: Record<string, unknown>;
  memory?: Record<string, unknown>;
  uptime_seconds?: number;
}

export interface NomicState {
  phase?: string;
  cycle?: number;
  loop_id?: string;
  last_update?: string;
}

export interface NomicHealth {
  healthy?: boolean;
  stalled?: boolean;
  last_activity?: string;
}

export interface Mode {
  name?: string;
  description?: string;
  builtin?: boolean;
}

export interface SimilarDebate {
  debate_id?: string;
  topic?: string;
  similarity?: number;
  outcome?: string;
}

export interface SettledTopic {
  topic?: string;
  consensus?: string;
  confidence?: number;
  debate_count?: number;
}

export interface ConsensusStats {
  total_topics?: number;
  settled_count?: number;
  average_confidence?: number;
}

export interface Dissent {
  agent?: string;
  topic?: string;
  position?: string;
  debate_id?: string;
}

export interface Memory {
  id?: string;
  content?: string;
  tier?: 'fast' | 'medium' | 'slow' | 'glacial';
  importance?: number;
  created_at?: string;
}

export interface TierStats {
  fast?: TierInfo;
  medium?: TierInfo;
  slow?: TierInfo;
  glacial?: TierInfo;
}

export interface TierInfo {
  count?: number;
  avg_importance?: number;
}

export interface Tournament {
  id?: string;
  name?: string;
  status?: string;
  participants?: number;
}

export interface TournamentStandings {
  tournament_id?: string;
  standings?: { rank?: number; agent?: string; points?: number }[];
}

export interface ReplaySummary {
  id?: string;
  debate_id?: string;
  event_count?: number;
  created_at?: string;
}

export interface Replay {
  id?: string;
  events?: Record<string, unknown>[];
  total_events?: number;
}

export interface DocumentSummary {
  id?: string;
  filename?: string;
  word_count?: number;
  preview?: string;
}

export interface Document {
  id?: string;
  filename?: string;
  content_type?: string;
  text?: string;
  page_count?: number;
  word_count?: number;
}

export interface SupportedFormats {
  formats?: { ext?: string; mime?: string; available?: boolean }[];
  max_size_mb?: number;
}

export interface VerificationStatus {
  z3_available?: boolean;
  lean_available?: boolean;
}

export interface VerificationResult {
  verified?: boolean;
  backend?: string;
  proof?: string;
  counterexample?: string;
}

export interface DisagreementStats {
  total_disagreements?: number;
  avg_severity?: number;
}

export interface RankingStats {
  total_agents?: number;
  total_matches?: number;
  avg_elo?: number;
}

export interface RelationshipSummary {
  total_relationships?: number;
  rivalries?: number;
  alliances?: number;
}

export interface RelationshipGraph {
  nodes?: { id?: string; elo?: number }[];
  edges?: { source?: string; target?: string; weight?: number }[];
}

export interface Relationship {
  agent_a?: string;
  agent_b?: string;
  debates?: number;
  wins_a?: number;
  wins_b?: number;
  relationship_type?: 'rival' | 'ally' | 'neutral';
}

export interface MomentsSummary {
  total_moments?: number;
  by_type?: Record<string, number>;
}

export interface Moment {
  id?: string;
  type?:
    | 'upset_victory'
    | 'position_reversal'
    | 'calibration_vindication'
    | 'alliance_shift'
    | 'consensus_breakthrough'
    | 'streak_achievement'
    | 'domain_mastery';
  agent?: string;
  description?: string;
  significance?: number;
  timestamp?: string;
}

export interface DashboardMetrics {
  debates_count?: number;
  consensus_rate?: number;
  avg_rounds?: number;
  top_agents?: LeaderboardEntry[];
  recent_debates?: DebateSummary[];
}

export interface TrendingTopic {
  title?: string;
  source?: 'hackernews' | 'reddit' | 'twitter';
  url?: string;
  score?: number;
}

export interface SchedulerStatus {
  state?: 'stopped' | 'running' | 'paused';
  run_id?: string;
  config?: {
    poll_interval_seconds?: number;
    max_debates_per_hour?: number;
    min_volume_threshold?: number;
    min_controversy_score?: number;
    dedup_window_hours?: number;
  };
  metrics?: {
    polls_completed?: number;
    topics_evaluated?: number;
    topics_filtered?: number;
    debates_created?: number;
    debates_failed?: number;
    duplicates_skipped?: number;
    last_poll_at?: number;
    last_debate_at?: number;
    uptime_seconds?: number;
  };
}

export interface ScheduledDebateRecord {
  id?: string;
  topic_hash?: string;
  topic_text?: string;
  platform?: string;
  category?: string;
  volume?: number;
  debate_id?: string;
  created_at?: number;
  consensus_reached?: boolean;
  confidence?: number;
  rounds_used?: number;
  scheduler_run_id?: string;
}

export interface APIError {
  error?: {
    /** Machine-readable error code */
    code?:
      | 'VALIDATION_ERROR'
      | 'INVALID_REQUEST'
      | 'NOT_FOUND'
      | 'UNAUTHORIZED'
      | 'FORBIDDEN'
      | 'RATE_LIMITED'
      | 'INTERNAL_ERROR'
      | 'SERVICE_UNAVAILABLE'
      | 'TIMEOUT';
    /** Human-readable error message */
    message?: string;
    /** HTTP status code */
    status?: number;
    /** Trace ID for debugging */
    trace_id?: string;
    /** Additional error details */
    details?: Record<string, unknown>;
    /** Suggested action to resolve the error */
    suggestion?: string;
  };
}

export interface ProbeReport {
  report_id?: string;
  target_agent?: string;
  probes_run?: number;
  vulnerabilities_found?: number;
  vulnerability_rate?: number;
  elo_penalty?: number;
  by_type?: Record<string, { passed?: number; failed?: number; severity?: string }>;
  summary?: { critical?: number; high?: number; medium?: number; low?: number };
}

export interface EmergentTrait {
  agent?: string;
  trait?: string;
  domain?: string;
  confidence?: number;
  evidence?: string[];
  detected_at?: string;
}

export interface CrossPollinationSuggestion {
  source_agent?: string;
  target_agent?: string;
  trait?: string;
  benefit_score?: number;
  rationale?: string;
}

export interface Insight {
  id?: string;
  type?: 'pattern' | 'consensus' | 'disagreement' | 'breakthrough' | 'risk';
  title?: string;
  description?: string;
  confidence?: number;
  agents_involved?: string[];
  evidence?: string[];
  created_at?: string;
}

export interface TeamCombination {
  agents?: string[];
  debates?: number;
  consensus_rate?: number;
  avg_rounds?: number;
  win_rate?: number;
}

export interface AgentRecommendation {
  agent?: string;
  score?: number;
  reasons?: string[];
  domain_fit?: number;
  trait_match?: number;
}

export interface EvolutionPattern {
  id?: string;
  type?: 'argument' | 'structure' | 'citation' | 'rhetorical';
  /** The extracted pattern text */
  pattern?: string;
  success_rate?: number;
  usage_count?: number;
  agents_using?: string[];
  /** Debate ID where pattern was first seen */
  extracted_from?: string;
  created_at?: string;
}

export interface EvolutionEvent {
  version?: number;
  timestamp?: string;
  strategy?: 'append' | 'replace' | 'refine';
  patterns_applied?: string[];
  success_rate_before?: number;
  success_rate_after?: number;
  /** Summary of changes made */
  prompt_diff?: string;
}
