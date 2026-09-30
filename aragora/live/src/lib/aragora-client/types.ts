/**
 * Aragora SDK Type Definitions
 *
 * Core types for the Aragora client library.
 */

// =============================================================================
// Core Types (matching SDK types for future migration)
// =============================================================================

export interface ConsensusResult {
  reached: boolean;
  conclusion?: string;
  final_answer?: string;
  confidence: number;
  agreement?: number;
  supporting_agents: string[];
  dissenting_agents?: string[];
}

export interface DebateMessage {
  agent_id: string;
  content: string;
  round: number;
  message_type?: 'proposal' | 'critique' | 'revision' | 'synthesis';
  timestamp?: string;
}

export interface DebateRound {
  round_number: number;
  messages: DebateMessage[];
}

export interface Debate {
  id?: string;
  debate_id: string;
  task: string;
  status: string;
  agents: string[];
  rounds: DebateRound[];
  consensus?: ConsensusResult;
  created_at?: string;
  completed_at?: string;
  metadata?: Record<string, unknown>;
}

export interface DebateCreateRequest {
  task: string;
  agents?: string[];
  max_rounds?: number;
  consensus_threshold?: number;
  enable_voting?: boolean;
  context?: string;
}

export interface DebateCreateResponse {
  debate_id: string;
  status: string;
  task: string;
}

export interface AgentProfile {
  agent_id: string;
  name: string;
  provider: string;
  elo_rating?: number;
  wins?: number;
  losses?: number;
  draws?: number;
  specializations?: string[];
}

export interface LeaderboardEntry {
  agent_id: string;
  elo_rating: number;
  rank: number;
  wins?: number;
  losses?: number;
  win_rate?: number;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  tier: string;
  owner_id: string;
  member_count: number;
  debates_used: number;
  debates_limit: number;
  settings: Record<string, unknown>;
  created_at: string;
}

export interface OrganizationMember {
  id: string;
  email: string;
  name: string;
  role: 'member' | 'admin' | 'owner';
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

/**
 * Represents a user's membership in an organization (multi-org support).
 * This is a junction record linking users to organizations with role info.
 */
export interface UserOrganization {
  /** User ID */
  user_id: string;
  /** Organization ID */
  org_id: string;
  /** Organization details */
  organization: Organization;
  /** User's role within this organization */
  role: 'member' | 'admin' | 'owner';
  /** Whether this is the user's default/active organization */
  is_default: boolean;
  /** When the user joined this organization */
  joined_at: string;
}

/**
 * Response for listing user's organizations.
 */
export interface UserOrganizationsResponse {
  /** List of organizations the user belongs to */
  organizations: UserOrganization[];
  /** ID of the currently active organization */
  active_org_id: string | null;
  /** Total count of organizations */
  total: number;
}

/**
 * Request to switch the active organization context.
 */
export interface SwitchOrganizationRequest {
  /** ID of the organization to switch to */
  org_id: string;
  /** Whether to set this as the default organization */
  set_as_default?: boolean;
}

/**
 * Response after switching organization context.
 */
export interface SwitchOrganizationResponse {
  /** Success status */
  success: boolean;
  /** The new active organization */
  organization: Organization;
  /** Updated access token with org context (if applicable) */
  access_token?: string;
}

export interface AnalyticsOverview {
  total_debates: number;
  active_debates: number;
  completed_debates: number;
  failed_debates: number;
  avg_debate_duration_seconds: number;
  consensus_rate: number;
  period_days: number;
}

export interface AnalyticsResponse {
  overview: AnalyticsOverview;
  top_agents: Array<{
    agent_id: string;
    debates_participated: number;
    wins: number;
    losses: number;
    draws: number;
    avg_contribution_score: number;
  }>;
  debates_by_day: Array<{ date: string; count: number }>;
}

// =============================================================================
// Client Configuration Types
// =============================================================================

export interface AragoraClientConfig {
  baseUrl: string;
  apiKey?: string;
  timeout?: number;
  headers?: Record<string, string>;
}

export interface RequestOptions {
  timeout?: number;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

// =============================================================================
// Billing Types
// =============================================================================

export interface BillingUsage {
  period_start: string;
  period_end: string;
  debates_used: number;
  debates_limit: number;
  api_calls: number;
  storage_mb: number;
  overage_charges: number;
}

export interface BillingPlan {
  id: string;
  name: string;
  price_monthly: number;
  price_yearly: number;
  debates_per_month: number;
  features: string[];
  is_popular?: boolean;
}

export interface BillingSubscription {
  id: string;
  plan_id: string;
  plan_name: string;
  status: 'active' | 'canceled' | 'past_due' | 'trialing';
  current_period_start: string;
  current_period_end: string;
  cancel_at_period_end: boolean;
  payment_method?: { type: string; last4?: string; brand?: string };
}

export interface BillingInvoice {
  id: string;
  amount: number;
  currency: string;
  status: 'paid' | 'open' | 'void' | 'uncollectible';
  created_at: string;
  paid_at?: string;
  invoice_pdf?: string;
  period_start: string;
  period_end: string;
}

// =============================================================================
// Analytics Types
// =============================================================================

export interface AnalyticsOverviewResponse {
  overview: AnalyticsOverview;
  top_agents: Array<{
    agent_id: string;
    debates_participated: number;
    wins: number;
    losses: number;
    draws: number;
    avg_contribution_score: number;
  }>;
  debates_by_day: Array<{ date: string; count: number }>;
}

export interface AgentPerformanceAnalytics {
  agent_id: string;
  total_debates: number;
  wins: number;
  losses: number;
  draws: number;
  win_rate: number;
  avg_rounds_to_consensus: number;
  contribution_scores: Array<{ debate_id: string; score: number }>;
  performance_trend: Array<{ date: string; elo: number }>;
}

export interface ConsensusPatternAnalytics {
  total_debates: number;
  consensus_reached: number;
  consensus_rate: number;
  avg_rounds_to_consensus: number;
  common_agreement_patterns: Array<{ pattern: string; frequency: number }>;
  dissent_reasons: Array<{ reason: string; count: number }>;
}

export interface RealTimeMetrics {
  active_debates: number;
  debates_per_minute: number;
  avg_response_time_ms: number;
  queue_depth: number;
  agent_utilization: Record<string, number>;
  error_rate: number;
}

// =============================================================================
// MFA Types
// =============================================================================

export interface MFASetupResponse {
  secret: string;
  qr_code: string;
  backup_codes: string[];
}

export interface MFAVerifyResponse {
  valid: boolean;
  message?: string;
}

export interface MFAStatusResponse {
  enabled: boolean;
  method: 'totp' | 'backup' | null;
  last_used?: string;
}

// =============================================================================
// Admin Types
// =============================================================================

export interface AdminUser {
  id: string;
  email: string;
  name: string;
  is_active: boolean;
  organization_id?: string;
  created_at: string;
  last_login_at?: string;
  roles: string[];
}

export interface AuditLogEntry {
  id: string;
  user_id: string;
  action: string;
  resource_type: string;
  resource_id: string;
  details: Record<string, unknown>;
  ip_address?: string;
  timestamp: string;
}

export interface SystemHealthResponse {
  status: 'healthy' | 'degraded' | 'unhealthy';
  services: Record<
    string,
    { status: 'up' | 'down' | 'degraded'; latency_ms?: number; last_check: string }
  >;
  database: { connected: boolean; latency_ms: number };
  cache: { connected: boolean; hit_rate: number };
}

// =============================================================================
// Evidence Types
// =============================================================================

export interface Evidence {
  id: string;
  debate_id: string;
  agent_id: string;
  content: string;
  source_type: 'web' | 'document' | 'api' | 'database' | 'user';
  source_url?: string;
  credibility_score: number;
  relevance_score: number;
  created_at: string;
  metadata?: Record<string, unknown>;
}

export interface EvidenceSearchResult {
  evidence: Evidence[];
  total: number;
  page: number;
  limit: number;
  facets?: { sources: Record<string, number>; agents: Record<string, number> };
}

export interface EvidenceCreateRequest {
  debate_id: string;
  content: string;
  source_type: Evidence['source_type'];
  source_url?: string;
  metadata?: Record<string, unknown>;
}

// =============================================================================
// Training Types
// =============================================================================

export interface TrainingExample {
  id: string;
  input: string;
  output: string;
  debate_id?: string;
  agent_id?: string;
  quality_score: number;
  labels?: string[];
  created_at: string;
}

export interface TrainingDataset {
  id: string;
  name: string;
  description?: string;
  example_count: number;
  format: 'jsonl' | 'csv' | 'parquet';
  status: 'pending' | 'generating' | 'ready' | 'failed';
  created_at: string;
  download_url?: string;
}

export interface TrainingExportRequest {
  name: string;
  format?: 'jsonl' | 'csv' | 'parquet';
  filters?: {
    debate_ids?: string[];
    agent_ids?: string[];
    min_quality_score?: number;
    date_from?: string;
    date_to?: string;
  };
}

// =============================================================================
// Tournament Types
// =============================================================================

export interface Tournament {
  id: string;
  name: string;
  description?: string;
  status: 'pending' | 'active' | 'completed' | 'cancelled';
  format: 'round_robin' | 'single_elimination' | 'double_elimination' | 'swiss';
  participants: string[];
  rounds: TournamentRound[];
  created_at: string;
  started_at?: string;
  completed_at?: string;
}

export interface TournamentRound {
  round_number: number;
  matches: TournamentMatch[];
  status: 'pending' | 'in_progress' | 'completed';
}

export interface TournamentMatch {
  id: string;
  participants: string[];
  winner?: string;
  debate_id?: string;
  scores: Record<string, number>;
}

export interface TournamentCreateRequest {
  name: string;
  description?: string;
  format: Tournament['format'];
  participants: string[];
  settings?: Record<string, unknown>;
}

// =============================================================================
// Pulse (Trending) Types
// =============================================================================

export interface TrendingTopic {
  topic: string;
  debate_count: number;
  growth_rate: number;
  top_agents: string[];
  sentiment: { positive: number; negative: number; neutral: number };
  related_topics: string[];
}

export interface PulseResponse {
  topics: TrendingTopic[];
  period: string;
  updated_at: string;
}

// =============================================================================
// Gallery Types
// =============================================================================

export interface GalleryDebate {
  id: string;
  debate_id: string;
  title: string;
  summary: string;
  featured: boolean;
  category: string;
  tags: string[];
  votes: number;
  views: number;
  created_at: string;
  debate_snapshot: Partial<Debate>;
}

export interface GalleryListResponse {
  debates: GalleryDebate[];
  total: number;
  page: number;
  limit: number;
  categories: string[];
}

// =============================================================================
// Moments Types
// =============================================================================

export interface AgentMoment {
  id: string;
  agent_id: string;
  debate_id: string;
  moment_type: 'breakthrough' | 'consensus' | 'challenge' | 'insight' | 'reversal';
  content: string;
  context: string;
  impact_score: number;
  round: number;
  created_at: string;
}

export interface MomentsListResponse {
  moments: AgentMoment[];
  total: number;
  page: number;
}

// =============================================================================
// Agent Detail Types
// =============================================================================

export interface AgentDetail extends AgentProfile {
  description?: string;
  created_at: string;
  debate_history: Array<{
    debate_id: string;
    task: string;
    result: 'win' | 'loss' | 'draw';
    elo_change: number;
    date: string;
  }>;
  performance_stats: {
    avg_rounds_to_consensus: number;
    avg_contribution_score: number;
    consensus_initiation_rate: number;
    critique_effectiveness: number;
  };
  badges: Array<{ id: string; name: string; description: string; earned_at: string }>;
}

// =============================================================================
// Nomic Admin Types
// =============================================================================

export interface NomicLoop {
  id: string;
  status: 'pending' | 'running' | 'paused' | 'completed' | 'failed';
  current_phase: number;
  total_phases: number;
  started_at?: string;
  completed_at?: string;
  result?: Record<string, unknown>;
  error?: string;
}

export interface NomicLoopCreateRequest {
  phases?: number;
  config?: Record<string, unknown>;
}

// =============================================================================
// Genesis Types
// =============================================================================

export interface GenesisAgent {
  id: string;
  generation: number;
  parent_ids: string[];
  traits: Record<string, number>;
  fitness_score: number;
  debate_performance: { wins: number; losses: number; avg_elo: number };
  created_at: string;
}

export interface GenesisGeneration {
  generation_number: number;
  population_size: number;
  top_agents: GenesisAgent[];
  avg_fitness: number;
  created_at: string;
}

export interface GenesisRunConfig {
  population_size?: number;
  generations?: number;
  mutation_rate?: number;
  crossover_rate?: number;
  selection_method?: 'tournament' | 'roulette' | 'elitism';
}

// =============================================================================
// Gauntlet Types
// =============================================================================

export interface GauntletRun {
  id: string;
  name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  config: GauntletConfig;
  progress: { completed_challenges: number; total_challenges: number; current_challenge?: string };
  results?: GauntletResults;
  started_at?: string;
  completed_at?: string;
}

export interface GauntletConfig {
  challenge_types: string[];
  difficulty_levels: string[];
  agents: string[];
  iterations_per_challenge?: number;
}

export interface GauntletResults {
  overall_score: number;
  challenge_scores: Record<string, number>;
  agent_rankings: Array<{ agent_id: string; score: number; challenges_passed: number }>;
  failure_analysis: Array<{ challenge: string; failure_rate: number; common_issues: string[] }>;
}

// =============================================================================
// Documents Types
// =============================================================================

export interface Document {
  id: string;
  name: string;
  path: string;
  type: string;
  size: number;
  mime_type: string;
  checksum: string;
  version: number;
  status: 'pending' | 'processing' | 'ready' | 'error';
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  created_by: string;
}

export interface DocumentVersion {
  version: number;
  checksum: string;
  size: number;
  created_at: string;
  created_by: string;
  change_summary?: string;
}

export interface DocumentSearchResult {
  documents: Document[];
  total: number;
  page: number;
  limit: number;
}

export interface DocumentCreateRequest {
  name: string;
  path?: string;
  content: string | Blob;
  metadata?: Record<string, unknown>;
}

export interface DocumentAuditEntry {
  id: string;
  document_id: string;
  action: 'create' | 'read' | 'update' | 'delete' | 'share' | 'download';
  user_id: string;
  user_email?: string;
  details?: Record<string, unknown>;
  ip_address?: string;
  timestamp: string;
}

// =============================================================================
// Control Plane Types
// =============================================================================

export interface ControlPlaneAgent {
  id: string;
  name: string;
  provider: string;
  status: 'active' | 'inactive' | 'suspended';
  config: Record<string, unknown>;
  rate_limits: { requests_per_minute: number; tokens_per_minute: number };
  usage: { requests_today: number; tokens_today: number };
  created_at: string;
  updated_at: string;
}

export interface ControlPlaneQuota {
  resource: string;
  limit: number;
  used: number;
  reset_at: string;
}

// =============================================================================
// Policy Types
// =============================================================================

export interface Policy {
  id: string;
  name: string;
  description?: string;
  type: 'content' | 'rate_limit' | 'access' | 'data_retention';
  rules: PolicyRule[];
  enabled: boolean;
  priority: number;
  created_at: string;
  updated_at: string;
}

export interface PolicyRule {
  id: string;
  condition: Record<string, unknown>;
  action: 'allow' | 'deny' | 'flag' | 'modify';
  parameters?: Record<string, unknown>;
}

export interface PolicyViolation {
  id: string;
  policy_id: string;
  policy_name: string;
  resource_type: string;
  resource_id: string;
  violation_type: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  details: Record<string, unknown>;
  resolved: boolean;
  resolved_at?: string;
  created_at: string;
}

export interface ComplianceReport {
  id: string;
  period_start: string;
  period_end: string;
  total_events: number;
  violations_count: number;
  violations_by_severity: Record<string, number>;
  violations_by_type: Record<string, number>;
  compliance_score: number;
  recommendations: string[];
  created_at: string;
}

// =============================================================================
// Workflow Types
// =============================================================================

export interface Workflow {
  id: string;
  name: string;
  description?: string;
  status: 'draft' | 'active' | 'archived';
  version: number;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  triggers: WorkflowTrigger[];
  created_at: string;
  updated_at: string;
}

export interface WorkflowNode {
  id: string;
  type: 'debate' | 'condition' | 'action' | 'transform' | 'webhook';
  position: { x: number; y: number };
  data: Record<string, unknown>;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  condition?: Record<string, unknown>;
}

export interface WorkflowTrigger {
  id: string;
  type: 'schedule' | 'webhook' | 'event' | 'manual';
  config: Record<string, unknown>;
  enabled: boolean;
}

export interface WorkflowExecution {
  id: string;
  workflow_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  current_node?: string;
  context: Record<string, unknown>;
  started_at: string;
  completed_at?: string;
  error?: string;
}

// =============================================================================
// Connector Types
// =============================================================================

export interface Connector {
  id: string;
  name: string;
  type: 'database' | 'api' | 'file' | 'queue' | 'stream';
  provider: string;
  status: 'connected' | 'disconnected' | 'error';
  config: Record<string, unknown>;
  last_sync?: string;
  created_at: string;
}

export interface ConnectorTestResult {
  success: boolean;
  latency_ms?: number;
  error?: string;
  details?: Record<string, unknown>;
}

export interface ConnectorSync {
  id: string;
  connector_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  records_processed: number;
  records_failed: number;
  started_at: string;
  completed_at?: string;
  error?: string;
}

// =============================================================================
// Repository Types
// =============================================================================

export interface Repository {
  id: string;
  name: string;
  url: string;
  provider: 'github' | 'gitlab' | 'bitbucket' | 'local';
  branch: string;
  status: 'pending' | 'indexing' | 'ready' | 'error';
  indexed_files: number;
  last_indexed?: string;
  created_at: string;
}

export interface RepositoryFile {
  path: string;
  name: string;
  type: 'file' | 'directory';
  size?: number;
  language?: string;
  indexed: boolean;
}

export interface CodeSearchResult {
  file_path: string;
  repository_id: string;
  matches: Array<{
    line_number: number;
    content: string;
    context_before: string[];
    context_after: string[];
  }>;
}

// =============================================================================
// Queue Types
// =============================================================================

export interface QueueJob {
  id: string;
  queue: string;
  type: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  priority: number;
  payload: Record<string, unknown>;
  result?: Record<string, unknown>;
  error?: string;
  attempts: number;
  max_attempts: number;
  scheduled_at?: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
}

export interface QueueStats {
  queue: string;
  pending: number;
  running: number;
  completed: number;
  failed: number;
  avg_processing_time_ms: number;
  throughput_per_minute: number;
}

// =============================================================================
// Extended Training Types
// =============================================================================

export interface TrainingJob {
  id: string;
  name: string;
  status: 'queued' | 'preparing' | 'training' | 'completed' | 'failed' | 'cancelled';
  model_type: string;
  dataset_id: string;
  config: TrainingJobConfig;
  metrics?: TrainingMetrics;
  progress: {
    current_epoch: number;
    total_epochs: number;
    current_step: number;
    total_steps: number;
  };
  created_at: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
}

export interface TrainingJobConfig {
  base_model?: string;
  epochs?: number;
  batch_size?: number;
  learning_rate?: number;
  warmup_steps?: number;
  custom_params?: Record<string, unknown>;
}

export interface TrainingMetrics {
  loss: number;
  accuracy?: number;
  eval_loss?: number;
  eval_accuracy?: number;
  training_time_seconds: number;
  history: Array<{ epoch: number; loss: number; accuracy?: number }>;
}

export interface TrainedModel {
  id: string;
  job_id: string;
  name: string;
  version: string;
  status: 'ready' | 'deploying' | 'deployed' | 'archived';
  metrics: TrainingMetrics;
  deployment?: { endpoint: string; replicas: number; last_request?: string };
  created_at: string;
}
