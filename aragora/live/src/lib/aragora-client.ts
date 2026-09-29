/**
 * Aragora SDK Client Wrapper for Frontend
 *
 * Singleton SDK client that integrates with AuthContext for token management
 * and BackendSelector for API URL configuration.
 *
 * Usage:
 * ```typescript
 * import { getClient, useAragoraClient } from '@/lib/aragora-client';
 *
 * // In components (hooks):
 * const client = useAragoraClient();
 * const debates = await client.debates.list();
 *
 * // Outside components (with token):
 * const client = getClient(token);
 * const health = await client.health();
 * ```
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

// BillingUsage, BillingPlan, BillingSubscription interfaces defined below with billing types

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
// Types
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
// Error Class
// =============================================================================

export class AragoraError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details?: Record<string, unknown>;

  constructor(message: string, code: string, status: number, details?: Record<string, unknown>) {
    super(message);
    this.name = 'AragoraError';
    this.code = code;
    this.status = status;
    this.details = details;
  }

  /** Create a user-friendly error message */
  toUserMessage(): string {
    switch (this.code) {
      case 'TIMEOUT':
        return 'Request timed out. Please try again or check your network connection.';
      case 'NETWORK_ERROR':
        return 'Network error. Please check your internet connection and try again.';
      case 'RATE_LIMITED':
        return 'Too many requests. Please wait a moment before trying again.';
      case 'UNAUTHORIZED':
        return 'Authentication failed. Please sign in again.';
      case 'FORBIDDEN':
        return 'Access denied. You do not have permission to perform this action.';
      case 'NOT_FOUND':
        return 'The requested resource was not found.';
      default:
        return this.message;
    }
  }
}

// =============================================================================
// HTTP Client
// =============================================================================

class HttpClient {
  private _baseUrl: string;
  private _apiKey?: string;
  private timeout: number;
  private defaultHeaders: Record<string, string>;

  get baseUrl(): string {
    return this._baseUrl;
  }

  get apiKey(): string | undefined {
    return this._apiKey;
  }

  constructor(config: AragoraClientConfig) {
    this._baseUrl = config.baseUrl.replace(/\/$/, '');
    this._apiKey = config.apiKey;
    this.timeout = config.timeout ?? 30000;
    this.defaultHeaders = { 'Content-Type': 'application/json', ...config.headers };

    if (this._apiKey) {
      this.defaultHeaders['Authorization'] = `Bearer ${this._apiKey}`;
    }
  }

  private async request<T>(
    method: string,
    path: string,
    data?: unknown,
    options?: RequestOptions,
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), options?.timeout ?? this.timeout);

    try {
      const response = await fetch(url, {
        method,
        headers: { ...this.defaultHeaders, ...options?.headers },
        body: data ? JSON.stringify(data) : undefined,
        signal: options?.signal ?? controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new AragoraError(
          errorData.error || `HTTP ${response.status}`,
          errorData.code || 'HTTP_ERROR',
          response.status,
          errorData,
        );
      }

      return response.json();
    } catch (error) {
      clearTimeout(timeoutId);

      if (error instanceof AragoraError) {
        throw error;
      }

      if (error instanceof Error) {
        if (error.name === 'AbortError') {
          throw new AragoraError('Request timed out', 'TIMEOUT', 408);
        }
        throw new AragoraError(error.message, 'NETWORK_ERROR', 0);
      }

      throw new AragoraError('Unknown error', 'UNKNOWN_ERROR', 0);
    }
  }

  async get<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>('GET', path, undefined, options);
  }

  async post<T>(path: string, data?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>('POST', path, data, options);
  }

  async put<T>(path: string, data?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>('PUT', path, data, options);
  }

  async delete<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>('DELETE', path, undefined, options);
  }
}

// =============================================================================
// API Classes (matching SDK structure)
// =============================================================================

class DebatesAPI {
  constructor(private http: HttpClient) {}

  async list(options?: { limit?: number; offset?: number; status?: string }) {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    if (options?.status) params.set('status', options.status);

    const query = params.toString();
    const path = query ? `/api/debates?${query}` : '/api/debates';
    return this.http.get<{ debates: unknown[] }>(path);
  }

  async get(debateId: string) {
    return this.http.get<unknown>(`/api/debates/${debateId}`);
  }

  async create(request: { task: string; agents?: string[]; max_rounds?: number }) {
    return this.http.post<{ debate_id: string }>('/api/debates', request);
  }
}

class AgentsAPI {
  constructor(private http: HttpClient) {}

  async list() {
    return this.http.get<{ agents: unknown[] }>('/api/agents');
  }

  async get(agentId: string) {
    return this.http.get<unknown>(`/api/agents/${agentId}`);
  }
}

class LeaderboardAPI {
  constructor(private http: HttpClient) {}

  async get(options?: { limit?: number }) {
    const params = options?.limit ? `?limit=${options.limit}` : '';
    return this.http.get<{ entries: unknown[] }>(`/api/leaderboard${params}`);
  }
}

class OrganizationsAPI {
  constructor(private http: HttpClient) {}

  async get(orgId: string) {
    return this.http.get<{ organization: unknown }>(`/api/org/${orgId}`);
  }

  async members(orgId: string) {
    return this.http.get<{ members: unknown[] }>(`/api/org/${orgId}/members`);
  }
}

/**
 * User Organizations API - Manages user's multi-org memberships
 */
class UserOrganizationsAPI {
  constructor(private http: HttpClient) {}

  /**
   * List all organizations the current user belongs to
   */
  async list(): Promise<{
    organizations: Array<{
      user_id: string;
      org_id: string;
      organization: { id: string; name: string; slug: string; tier: string; owner_id: string };
      role: 'member' | 'admin' | 'owner';
      is_default: boolean;
      joined_at: string;
    }>;
    active_org_id: string | null;
    total: number;
  }> {
    return this.http.get('/api/v1/user/organizations');
  }

  /**
   * Switch to a different organization context
   */
  async switch(
    orgId: string,
    setAsDefault = false,
  ): Promise<{
    success: boolean;
    organization: { id: string; name: string; slug: string; tier: string; owner_id: string };
    access_token?: string;
  }> {
    return this.http.post('/api/v1/user/organizations/switch', {
      org_id: orgId,
      set_as_default: setAsDefault,
    });
  }

  /**
   * Set a default organization for the user
   */
  async setDefault(orgId: string): Promise<{ success: boolean }> {
    return this.http.post('/api/v1/user/organizations/default', { org_id: orgId });
  }

  /**
   * Leave an organization (user removes themselves)
   */
  async leave(orgId: string): Promise<{ success: boolean }> {
    return this.http.delete(`/api/v1/user/organizations/${orgId}`);
  }
}

// Billing Types
export interface BillingPlan {
  id: string;
  name: string;
  price_monthly_cents: number;
  price_monthly: string;
  features: {
    debates_per_month: number;
    users_per_org: number;
    api_access: boolean;
    all_agents: boolean;
    custom_agents: boolean;
    sso_enabled: boolean;
    audit_logs: boolean;
    priority_support: boolean;
  };
}

export interface BillingUsage {
  debates_used: number;
  debates_limit: number;
  debates_remaining: number;
  tokens_used: number;
  tokens_in: number;
  tokens_out: number;
  estimated_cost_usd: number;
  cost_breakdown?: { input_cost: number; output_cost: number; total: number };
  cost_by_provider?: Record<string, string>;
  period_start: string | null;
  period_end: string | null;
}

export interface BillingSubscription {
  tier: string;
  status: string;
  is_active: boolean;
  organization?: { id: string; name: string };
  limits?: {
    debates_per_month: number;
    users_per_org: number;
    api_access: boolean;
    all_agents: boolean;
    custom_agents: boolean;
    sso_enabled: boolean;
    audit_logs: boolean;
    priority_support: boolean;
    price_monthly_cents: number;
  };
  current_period_end?: string;
  cancel_at_period_end?: boolean;
  trial_start?: string;
  trial_end?: string;
  is_trialing?: boolean;
  payment_failed?: boolean;
}

export interface BillingInvoice {
  id: string;
  number: string;
  status: string;
  amount_due: number;
  amount_paid: number;
  currency: string;
  created: string;
  period_start: string | null;
  period_end: string | null;
  hosted_invoice_url: string;
  invoice_pdf: string;
}

export interface UsageForecast {
  current_usage: { debates: number; debates_limit: number };
  projection: {
    debates_end_of_cycle: number;
    debates_per_day: number;
    tokens_per_day: number;
    cost_end_of_cycle_usd: number;
  };
  days_remaining: number;
  days_elapsed: number;
  will_hit_limit: boolean;
  debates_overage: number;
  tier_recommendation?: { recommended_tier: string; debates_limit: number; price_monthly: string };
}

class BillingAPI {
  constructor(private http: HttpClient) {}

  async usage(): Promise<{ usage: BillingUsage }> {
    return this.http.get<{ usage: BillingUsage }>('/api/billing/usage');
  }

  async subscription(): Promise<{ subscription: BillingSubscription }> {
    return this.http.get<{ subscription: BillingSubscription }>('/api/billing/subscription');
  }

  async plans(): Promise<{ plans: BillingPlan[] }> {
    return this.http.get<{ plans: BillingPlan[] }>('/api/billing/plans');
  }

  async invoices(limit = 10): Promise<{ invoices: BillingInvoice[] }> {
    return this.http.get<{ invoices: BillingInvoice[] }>(`/api/billing/invoices?limit=${limit}`);
  }

  async forecast(): Promise<{ forecast: UsageForecast }> {
    return this.http.get<{ forecast: UsageForecast }>('/api/billing/usage/forecast');
  }

  async createCheckout(
    tier: string,
    successUrl: string,
    cancelUrl: string,
  ): Promise<{ checkout: { id: string; url: string } }> {
    return this.http.post('/api/billing/checkout', {
      tier,
      success_url: successUrl,
      cancel_url: cancelUrl,
    });
  }

  async createPortal(returnUrl: string): Promise<{ portal: { url: string } }> {
    return this.http.post('/api/billing/portal', { return_url: returnUrl });
  }

  async cancelSubscription(): Promise<{ message: string; subscription: unknown }> {
    return this.http.post('/api/billing/cancel', {});
  }

  async resumeSubscription(): Promise<{ message: string; subscription: unknown }> {
    return this.http.post('/api/billing/resume', {});
  }

  async exportUsage(startDate?: string, endDate?: string): Promise<Blob> {
    const params = new URLSearchParams();
    if (startDate) params.set('start', startDate);
    if (endDate) params.set('end', endDate);
    const query = params.toString();
    const path = query ? `/api/billing/usage/export?${query}` : '/api/billing/usage/export';

    // This returns CSV data, so we need raw response
    const response = await fetch(this.http.baseUrl + path, {
      headers: this.http.apiKey ? { Authorization: `Bearer ${this.http.apiKey}` } : {},
    });
    return response.blob();
  }
}

// =============================================================================
// Analytics Types
// =============================================================================

export interface AnalyticsSummary {
  total_debates: number;
  total_messages: number;
  consensus_rate: number;
  avg_debate_duration_ms: number;
  active_users_24h: number;
  top_topics: Array<{ topic: string; count: number }>;
}

export interface FindingsTrend {
  date: string;
  findings_count: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
}

export interface RemediationMetrics {
  total_findings: number;
  remediated: number;
  pending: number;
  avg_remediation_time_hours: number;
  remediation_rate: number;
}

export interface AgentMetrics {
  agent_id: string;
  name: string;
  debates_participated: number;
  avg_message_length: number;
  consensus_contribution: number;
  response_time_ms: number;
  elo_rating?: number;
}

export interface CostAnalysis {
  total_cost_usd: number;
  cost_by_model: Record<string, number>;
  cost_by_debate_type: Record<string, number>;
  projected_monthly_cost: number;
  cost_trend: Array<{ date: string; cost: number }>;
}

export interface ComplianceScore {
  overall_score: number;
  categories: Array<{ category: string; score: number; max_score: number; findings: number }>;
  last_audit: string;
}

export interface HeatmapData {
  x_labels: string[];
  y_labels: string[];
  values: number[][];
  max_value: number;
}

export interface DisagreementStats {
  total_disagreements: number;
  avg_disagreement_intensity: number;
  resolved_rate: number;
  top_disagreement_topics: Array<{ topic: string; count: number }>;
}

class AnalyticsAPI {
  constructor(private http: HttpClient) {}

  async overview(days = 30) {
    return this.http.get<unknown>(`/api/analytics?days=${days}`);
  }

  /** Dashboard summary metrics */
  async summary(): Promise<{ summary: AnalyticsSummary }> {
    return this.http.get('/api/analytics/summary');
  }

  /** Finding trends over time */
  async findingsTrends(days = 30): Promise<{ trends: FindingsTrend[] }> {
    return this.http.get(`/api/analytics/trends/findings?days=${days}`);
  }

  /** Remediation metrics */
  async remediation(): Promise<{ metrics: RemediationMetrics }> {
    return this.http.get('/api/analytics/remediation');
  }

  /** Agent performance metrics */
  async agents(): Promise<{ agents: AgentMetrics[] }> {
    return this.http.get('/api/analytics/agents');
  }

  /** Cost analysis */
  async cost(days = 30): Promise<{ analysis: CostAnalysis }> {
    return this.http.get(`/api/analytics/cost?days=${days}`);
  }

  /** Compliance scorecard */
  async compliance(): Promise<{ compliance: ComplianceScore }> {
    return this.http.get('/api/analytics/compliance');
  }

  /** Risk heatmap data */
  async heatmap(): Promise<{ heatmap: HeatmapData }> {
    return this.http.get('/api/analytics/heatmap');
  }

  /** Disagreement statistics */
  async disagreements(): Promise<{ stats: DisagreementStats }> {
    return this.http.get('/api/analytics/disagreements');
  }

  /** Role rotation statistics */
  async roleRotation(): Promise<{ stats: unknown }> {
    return this.http.get('/api/analytics/role-rotation');
  }

  /** Early stopping statistics */
  async earlyStops(): Promise<{ stats: unknown }> {
    return this.http.get('/api/analytics/early-stops');
  }

  /** Consensus quality metrics */
  async consensusQuality(): Promise<{ stats: unknown }> {
    return this.http.get('/api/analytics/consensus-quality');
  }
}

// =============================================================================
// MFA API
// =============================================================================

export interface MFASetupResponse {
  secret: string;
  provisioning_uri: string;
  message: string;
}

export interface MFAEnableResponse {
  message: string;
  backup_codes: string[];
  warning: string;
}

export interface MFAVerifyResponse {
  message: string;
  user: Record<string, unknown>;
  tokens: { access_token: string; refresh_token: string; token_type: string; expires_in: number };
  backup_codes_remaining?: number;
  backup_codes_warning?: string;
}

export interface MFABackupCodesResponse {
  message: string;
  backup_codes: string[];
  warning: string;
}

class MFAAPI {
  constructor(private http: HttpClient) {}

  /**
   * Initialize MFA setup - generates TOTP secret and provisioning URI.
   * User should scan the QR code with their authenticator app.
   */
  async setup(): Promise<MFASetupResponse> {
    return this.http.post<MFASetupResponse>('/api/auth/mfa/setup', {});
  }

  /**
   * Enable MFA after verifying the setup code from authenticator app.
   * Returns backup codes that user should save.
   */
  async enable(code: string): Promise<MFAEnableResponse> {
    return this.http.post<MFAEnableResponse>('/api/auth/mfa/enable', { code });
  }

  /**
   * Disable MFA for the user.
   * Requires either current MFA code or password.
   */
  async disable(options: { code?: string; password?: string }): Promise<{ message: string }> {
    return this.http.post<{ message: string }>('/api/auth/mfa/disable', options);
  }

  /**
   * Verify MFA code during login (after receiving pending token).
   * Returns full authentication tokens on success.
   */
  async verify(pendingToken: string, code: string): Promise<MFAVerifyResponse> {
    return this.http.post<MFAVerifyResponse>('/api/auth/mfa/verify', {
      pending_token: pendingToken,
      code,
    });
  }

  /**
   * Regenerate backup codes.
   * Requires current MFA code for verification.
   */
  async regenerateBackupCodes(code: string): Promise<MFABackupCodesResponse> {
    return this.http.post<MFABackupCodesResponse>('/api/auth/mfa/backup-codes', { code });
  }
}

// =============================================================================
// Admin API (not in SDK, specific to admin console)
// =============================================================================

interface TierRevenue {
  count: number;
  price_cents: number;
  mrr_cents: number;
}

interface RevenueResponse {
  revenue: {
    mrr_cents: number;
    mrr_dollars: number;
    arr_dollars: number;
    tier_breakdown: Record<string, TierRevenue>;
    total_organizations: number;
    paying_organizations: number;
  };
}

interface AdminStatsResponse {
  stats: {
    total_users: number;
    active_users: number;
    total_organizations: number;
    tier_distribution: Record<string, number>;
    total_debates_this_month: number;
    users_active_24h: number;
    new_users_7d: number;
    new_orgs_7d: number;
  };
}

interface AdminUsersResponse {
  users: Array<{
    id: string;
    email: string;
    name: string;
    role: string;
    org_id: string | null;
    is_active: boolean;
    created_at: string;
    last_login_at: string | null;
  }>;
  total: number;
  limit: number;
  offset: number;
}

interface AdminOrganizationsResponse {
  organizations: Array<{
    id: string;
    name: string;
    slug: string;
    tier: string;
    owner_id: string;
    member_count: number;
    debates_used: number;
    debates_limit: number;
    created_at: string;
  }>;
  total: number;
  limit: number;
  offset: number;
}

interface HealthStatus {
  status: 'healthy' | 'degraded' | 'unhealthy';
  uptime_seconds: number;
  version: string;
  components: {
    database: { status: string; latency_ms?: number };
    agents: { status: string; available: number; total: number };
    memory: { status: string; usage_mb?: number };
    websocket: { status: string; connections: number };
  };
  timestamp: string;
}

interface CircuitBreakerState {
  agent: string;
  state: 'closed' | 'open' | 'half_open';
  failures: number;
  last_failure?: string;
  last_success?: string;
}

interface RecentError {
  id: string;
  timestamp: string;
  level: string;
  message: string;
  endpoint?: string;
  user_id?: string;
}

interface RateLimitState {
  endpoint: string;
  limit: number;
  remaining: number;
  reset_at: string;
}

class AdminAPI {
  constructor(private http: HttpClient) {}

  async revenue(): Promise<RevenueResponse> {
    return this.http.get<RevenueResponse>('/api/admin/revenue');
  }

  async stats(): Promise<AdminStatsResponse> {
    return this.http.get<AdminStatsResponse>('/api/admin/stats');
  }

  async users(options?: {
    limit?: number;
    offset?: number;
    search?: string;
  }): Promise<AdminUsersResponse> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    if (options?.search) params.set('search', options.search);

    const query = params.toString();
    const path = query ? `/api/admin/users?${query}` : '/api/admin/users';
    return this.http.get<AdminUsersResponse>(path);
  }

  async organizations(options?: {
    limit?: number;
    offset?: number;
    tier?: string;
  }): Promise<AdminOrganizationsResponse> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    if (options?.tier) params.set('tier', options.tier);

    const query = params.toString();
    const path = query ? `/api/admin/organizations?${query}` : '/api/admin/organizations';
    return this.http.get<AdminOrganizationsResponse>(path);
  }
}

// =============================================================================
// Training API (for ML training data exports)
// =============================================================================

interface TrainingExportOptions {
  min_confidence?: number;
  min_success_rate?: number;
  limit?: number;
  offset?: number;
  include_critiques?: boolean;
  include_patterns?: boolean;
  include_debates?: boolean;
  format?: 'json' | 'jsonl';
}

interface DPOExportOptions {
  min_confidence_diff?: number;
  limit?: number;
  offset?: number;
  format?: 'json' | 'jsonl';
}

interface GauntletExportOptions {
  persona?: 'gdpr' | 'hipaa' | 'ai_act' | 'all';
  min_severity?: number;
  limit?: number;
  offset?: number;
  format?: 'json' | 'jsonl';
}

interface TrainingStatsResponse {
  stats: {
    sft_available: number;
    dpo_available: number;
    gauntlet_available: number;
    total_debates: number;
    debates_with_consensus: number;
    last_export?: string;
  };
}

interface TrainingFormatsResponse {
  formats: {
    sft: { schema: object; description: string };
    dpo: { schema: object; description: string };
    gauntlet: { schema: object; description: string };
  };
}

interface TrainingExportResponse {
  data: unknown[];
  total: number;
  format: string;
  exported_at: string;
}

// =============================================================================
// Evidence Types
// =============================================================================

export interface EvidenceSnippet {
  id: string;
  source: string;
  title: string;
  snippet: string;
  url?: string;
  reliability_score: number;
  freshness_score?: number;
  quality_score?: number;
  metadata?: Record<string, unknown>;
  collected_at?: string;
}

export interface EvidenceSearchOptions {
  query: string;
  limit?: number;
  source?: string;
  min_reliability?: number;
  context?: {
    topic?: string;
    keywords?: string[];
    required_topics?: string[];
    preferred_sources?: string[];
    blocked_sources?: string[];
    max_age_days?: number;
    min_word_count?: number;
    require_citations?: boolean;
  };
}

export interface EvidenceCollectOptions {
  task: string;
  connectors?: string[];
  debate_id?: string;
  round?: number;
}

export interface EvidenceListOptions {
  limit?: number;
  offset?: number;
  source?: string;
  min_reliability?: number;
}

export interface EvidenceStatistics {
  total_evidence: number;
  by_source: Record<string, number>;
  average_reliability: number;
  average_quality?: number;
  last_collected?: string;
}

interface EvidenceListResponse {
  evidence: EvidenceSnippet[];
  total: number;
  limit: number;
  offset: number;
}

interface EvidenceSearchResponse {
  query: string;
  results: EvidenceSnippet[];
  count: number;
}

interface EvidenceCollectResponse {
  task: string;
  keywords: string[];
  snippets: EvidenceSnippet[];
  count: number;
  total_searched: number;
  average_reliability: number;
  average_freshness: number;
  saved_ids: string[];
  debate_id?: string;
}

// =============================================================================
// Evidence API
// =============================================================================

class EvidenceAPI {
  constructor(private http: HttpClient) {}

  async list(options?: EvidenceListOptions): Promise<EvidenceListResponse> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    if (options?.source) params.set('source', options.source);
    if (options?.min_reliability !== undefined)
      params.set('min_reliability', String(options.min_reliability));

    const query = params.toString();
    const path = query ? `/api/evidence?${query}` : '/api/evidence';
    return this.http.get<EvidenceListResponse>(path);
  }

  async get(id: string): Promise<{ evidence: EvidenceSnippet }> {
    return this.http.get<{ evidence: EvidenceSnippet }>(`/api/evidence/${id}`);
  }

  async search(options: EvidenceSearchOptions): Promise<EvidenceSearchResponse> {
    return this.http.post<EvidenceSearchResponse>('/api/evidence/search', options);
  }

  async collect(options: EvidenceCollectOptions): Promise<EvidenceCollectResponse> {
    return this.http.post<EvidenceCollectResponse>('/api/evidence/collect', options);
  }

  async getDebateEvidence(
    debateId: string,
    round?: number,
  ): Promise<{
    debate_id: string;
    round: number | null;
    evidence: EvidenceSnippet[];
    count: number;
  }> {
    const params = round !== undefined ? `?round=${round}` : '';
    return this.http.get(`/api/evidence/debate/${debateId}${params}`);
  }

  async associateWithDebate(
    debateId: string,
    evidenceIds: string[],
    round?: number,
  ): Promise<{ debate_id: string; associated: string[]; count: number }> {
    return this.http.post(`/api/evidence/debate/${debateId}`, { evidence_ids: evidenceIds, round });
  }

  async delete(id: string): Promise<{ deleted: boolean; evidence_id: string }> {
    return this.http.delete<{ deleted: boolean; evidence_id: string }>(`/api/evidence/${id}`);
  }

  async statistics(): Promise<{ statistics: EvidenceStatistics }> {
    return this.http.get<{ statistics: EvidenceStatistics }>('/api/evidence/statistics');
  }
}

// =============================================================================
// Training API
// =============================================================================

class TrainingAPI {
  constructor(private http: HttpClient) {}

  async stats(): Promise<TrainingStatsResponse> {
    return this.http.get<TrainingStatsResponse>('/api/training/stats');
  }

  async formats(): Promise<TrainingFormatsResponse> {
    return this.http.get<TrainingFormatsResponse>('/api/training/formats');
  }

  async exportSFT(options?: TrainingExportOptions): Promise<TrainingExportResponse> {
    const params = new URLSearchParams();
    if (options?.min_confidence !== undefined)
      params.set('min_confidence', String(options.min_confidence));
    if (options?.min_success_rate !== undefined)
      params.set('min_success_rate', String(options.min_success_rate));
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    if (options?.include_critiques !== undefined)
      params.set('include_critiques', String(options.include_critiques));
    if (options?.include_patterns !== undefined)
      params.set('include_patterns', String(options.include_patterns));
    if (options?.include_debates !== undefined)
      params.set('include_debates', String(options.include_debates));
    if (options?.format) params.set('format', options.format);

    const query = params.toString();
    const path = query ? `/api/training/export/sft?${query}` : '/api/training/export/sft';
    return this.http.get<TrainingExportResponse>(path);
  }

  async exportDPO(options?: DPOExportOptions): Promise<TrainingExportResponse> {
    const params = new URLSearchParams();
    if (options?.min_confidence_diff !== undefined)
      params.set('min_confidence_diff', String(options.min_confidence_diff));
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    if (options?.format) params.set('format', options.format);

    const query = params.toString();
    const path = query ? `/api/training/export/dpo?${query}` : '/api/training/export/dpo';
    return this.http.get<TrainingExportResponse>(path);
  }

  async exportGauntlet(options?: GauntletExportOptions): Promise<TrainingExportResponse> {
    const params = new URLSearchParams();
    if (options?.persona) params.set('persona', options.persona);
    if (options?.min_severity !== undefined)
      params.set('min_severity', String(options.min_severity));
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    if (options?.format) params.set('format', options.format);

    const query = params.toString();
    const path = query ? `/api/training/export/gauntlet?${query}` : '/api/training/export/gauntlet';
    return this.http.get<TrainingExportResponse>(path);
  }

  // === Job Management (Enterprise Training Pipeline) ===

  async listJobs(options?: {
    status?: 'pending' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
    job_type?: 'sft' | 'dpo' | 'rlhf' | 'evaluation';
    limit?: number;
    offset?: number;
  }): Promise<{ jobs: TrainingJob[]; total: number }> {
    const params = new URLSearchParams();
    if (options?.status) params.set('status', options.status);
    if (options?.job_type) params.set('job_type', options.job_type);
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    const query = params.toString();
    return this.http.get(`/api/training/jobs${query ? `?${query}` : ''}`);
  }

  async getJob(jobId: string): Promise<{ job: TrainingJob }> {
    return this.http.get(`/api/training/jobs/${jobId}`);
  }

  async createJob(config: TrainingJobConfig): Promise<{ job: TrainingJob }> {
    return this.http.post('/api/training/jobs', config);
  }

  async startJob(jobId: string): Promise<{ job: TrainingJob; message: string }> {
    return this.http.post(`/api/training/jobs/${jobId}/start`, {});
  }

  async cancelJob(jobId: string): Promise<{ success: boolean; message: string }> {
    return this.http.post(`/api/training/jobs/${jobId}/cancel`, {});
  }

  async getJobMetrics(jobId: string): Promise<{ metrics: TrainingJobMetrics }> {
    return this.http.get(`/api/training/jobs/${jobId}/metrics`);
  }

  async getJobArtifacts(jobId: string): Promise<{ artifacts: TrainingJobArtifacts }> {
    return this.http.get(`/api/training/jobs/${jobId}/artifacts`);
  }

  async deleteJob(jobId: string): Promise<{ success: boolean }> {
    return this.http.delete(`/api/training/jobs/${jobId}`);
  }
}

class SystemAPI {
  constructor(private http: HttpClient) {}

  async health(): Promise<HealthStatus> {
    return this.http.get<HealthStatus>('/api/health');
  }

  async circuitBreakers(): Promise<{ breakers: CircuitBreakerState[] }> {
    return this.http.get<{ breakers: CircuitBreakerState[] }>('/api/system/circuit-breakers');
  }

  async errors(limit = 20): Promise<{ errors: RecentError[] }> {
    return this.http.get<{ errors: RecentError[] }>(`/api/system/errors?limit=${limit}`);
  }

  async rateLimits(): Promise<{ limits: RateLimitState[] }> {
    return this.http.get<{ limits: RateLimitState[] }>('/api/system/rate-limits');
  }
}

// =============================================================================
// Tournaments API
// =============================================================================

export interface Tournament {
  id: string;
  name: string;
  topic: string;
  status: 'pending' | 'in_progress' | 'completed';
  bracket_type: 'single_elimination' | 'double_elimination' | 'round_robin';
  participants: string[];
  matches: TournamentMatch[];
  winner?: string;
  created_at: string;
  completed_at?: string;
}

export interface TournamentMatch {
  id: string;
  round: number;
  participant1: string;
  participant2: string;
  winner?: string;
  debate_id?: string;
  status: 'pending' | 'in_progress' | 'completed';
}

export interface TournamentStanding {
  agent_id: string;
  wins: number;
  losses: number;
  points: number;
  rank: number;
}

class TournamentsAPI {
  constructor(private http: HttpClient) {}

  async list(options?: {
    limit?: number;
    status?: string;
  }): Promise<{ tournaments: Tournament[] }> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.status) params.set('status', options.status);
    const query = params.toString();
    return this.http.get(`/api/tournaments${query ? `?${query}` : ''}`);
  }

  async get(id: string): Promise<{ tournament: Tournament }> {
    return this.http.get(`/api/tournaments/${id}`);
  }

  async create(data: {
    name: string;
    topic: string;
    participants: string[];
    bracket_type?: string;
  }): Promise<{ tournament: Tournament }> {
    return this.http.post('/api/tournaments/create', data);
  }

  async bracket(id: string): Promise<{ bracket: TournamentMatch[] }> {
    return this.http.get(`/api/tournaments/${id}/bracket`);
  }

  async standings(id: string): Promise<{ standings: TournamentStanding[] }> {
    return this.http.get(`/api/tournaments/${id}/standings`);
  }

  async matches(id: string): Promise<{ matches: TournamentMatch[] }> {
    return this.http.get(`/api/tournaments/${id}/matches`);
  }

  async advance(id: string): Promise<{ tournament: Tournament }> {
    return this.http.post(`/api/tournaments/${id}/advance`, {});
  }

  async results(): Promise<{ results: Tournament[] }> {
    return this.http.get('/api/tournaments/results');
  }
}

// =============================================================================
// Pulse API (Trending Topics)
// =============================================================================

export interface TrendingTopic {
  topic: string;
  score: number;
  category: string;
  source: string;
  timestamp: string;
}

export interface PulseStats {
  total_topics: number;
  categories: Record<string, number>;
  last_updated: string;
}

class PulseAPI {
  constructor(private http: HttpClient) {}

  async trending(options?: {
    limit?: number;
    category?: string;
  }): Promise<{ topics: TrendingTopic[] }> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.category) params.set('category', options.category);
    const query = params.toString();
    return this.http.get(`/api/pulse/trending${query ? `?${query}` : ''}`);
  }

  async categories(): Promise<{ categories: string[] }> {
    return this.http.get('/api/pulse/categories');
  }

  async suggest(topic: string): Promise<{ suggestions: string[] }> {
    return this.http.post('/api/pulse/suggest', { topic });
  }

  async stats(): Promise<{ stats: PulseStats }> {
    return this.http.get('/api/pulse/stats');
  }

  async analytics(): Promise<{ analytics: unknown }> {
    return this.http.get('/api/pulse/analytics');
  }

  async debateTopic(topicId: string): Promise<{ debate_id: string }> {
    return this.http.post('/api/pulse/debate-topic', { topic_id: topicId });
  }
}

// =============================================================================
// Gallery API (Public Debates Showcase)
// =============================================================================

export interface GalleryEntry {
  id: string;
  debate_id: string;
  title: string;
  summary: string;
  agents: string[];
  consensus_reached: boolean;
  featured: boolean;
  views: number;
  created_at: string;
}

class GalleryAPI {
  constructor(private http: HttpClient) {}

  async list(options?: {
    limit?: number;
    featured?: boolean;
  }): Promise<{ entries: GalleryEntry[] }> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.featured !== undefined) params.set('featured', String(options.featured));
    const query = params.toString();
    return this.http.get(`/api/gallery${query ? `?${query}` : ''}`);
  }

  async get(debateId: string): Promise<{ entry: GalleryEntry }> {
    return this.http.get(`/api/gallery/${debateId}`);
  }

  async embed(debateId: string): Promise<{ embed_url: string; embed_html: string }> {
    return this.http.get(`/api/gallery/${debateId}/embed`);
  }
}

// =============================================================================
// Moments API (Notable Debate Moments)
// =============================================================================

export interface DebateMoment {
  id: string;
  debate_id: string;
  type: 'flip' | 'breakthrough' | 'consensus' | 'disagreement' | 'insight';
  agent_id: string;
  content: string;
  round: number;
  score: number;
  timestamp: string;
}

class MomentsAPI {
  constructor(private http: HttpClient) {}

  async recent(limit = 20): Promise<{ moments: DebateMoment[] }> {
    return this.http.get(`/api/moments/recent?limit=${limit}`);
  }

  async trending(): Promise<{ moments: DebateMoment[] }> {
    return this.http.get('/api/moments/trending');
  }

  async byType(type: string, limit = 20): Promise<{ moments: DebateMoment[] }> {
    return this.http.get(`/api/moments/by-type/${type}?limit=${limit}`);
  }

  async timeline(debateId: string): Promise<{ moments: DebateMoment[] }> {
    return this.http.get(`/api/moments/timeline?debate_id=${debateId}`);
  }

  async summary(): Promise<{ summary: Record<string, number> }> {
    return this.http.get('/api/moments/summary');
  }
}

// =============================================================================
// Agent Detail API (Extended Agent Info)
// =============================================================================

export interface AgentHistory {
  debate_id: string;
  task: string;
  outcome: 'win' | 'loss' | 'draw';
  elo_change: number;
  date: string;
}

export interface AgentNetwork {
  allies: Array<{ agent_id: string; synergy_score: number; matches: number }>;
  rivals: Array<{ agent_id: string; rivalry_score: number; matches: number }>;
}

export interface AgentPerformance {
  agent_id: string;
  total_debates: number;
  wins: number;
  losses: number;
  draws: number;
  win_rate: number;
  avg_elo_gain: number;
  domains: Record<string, { wins: number; losses: number }>;
}

class AgentDetailAPI {
  constructor(private http: HttpClient) {}

  async history(agentId: string, limit = 20): Promise<{ history: AgentHistory[] }> {
    return this.http.get(`/api/agent/${agentId}/history?limit=${limit}`);
  }

  async network(agentId: string): Promise<AgentNetwork> {
    return this.http.get(`/api/agent/${agentId}/network`);
  }

  async performance(agentId: string): Promise<{ performance: AgentPerformance }> {
    return this.http.get(`/api/agent/${agentId}/performance`);
  }

  async profile(agentId: string): Promise<{ profile: unknown }> {
    return this.http.get(`/api/agent/${agentId}/profile`);
  }

  async consistency(agentId: string): Promise<{ consistency: unknown }> {
    return this.http.get(`/api/agent/${agentId}/consistency`);
  }

  async calibration(agentId: string): Promise<{ calibration: unknown }> {
    return this.http.get(`/api/agent/${agentId}/calibration`);
  }

  async domains(agentId: string): Promise<{ domains: Record<string, unknown> }> {
    return this.http.get(`/api/agent/${agentId}/domains`);
  }

  async headToHead(agentId: string, opponentId: string): Promise<{ stats: unknown }> {
    return this.http.get(`/api/agent/${agentId}/head-to-head/${opponentId}`);
  }

  async compare(agents: string[]): Promise<{ comparison: unknown }> {
    const params = agents.map((a) => `agents=${a}`).join('&');
    return this.http.get(`/api/agent/compare?${params}`);
  }
}

// =============================================================================
// Nomic Admin API (Loop Management)
// =============================================================================

export interface NomicStatus {
  running: boolean;
  current_phase: string | null;
  cycle_id: string | null;
  state_machine: Record<string, unknown> | null;
  metrics: Record<string, unknown> | null;
  circuit_breakers: { open: string[]; details: Record<string, unknown> } | null;
  last_checkpoint: string | null;
  stuck_detection: { is_stuck: boolean; stuck_duration_seconds: number };
  errors: string[];
}

export interface NomicCircuitBreakers {
  circuit_breakers: Record<string, unknown>;
  open_circuits: string[];
  total_count: number;
}

class NomicAdminAPI {
  constructor(private http: HttpClient) {}

  async status(): Promise<NomicStatus> {
    return this.http.get('/api/admin/nomic/status');
  }

  async circuitBreakers(): Promise<NomicCircuitBreakers> {
    return this.http.get('/api/admin/nomic/circuit-breakers');
  }

  async reset(options: {
    target_phase: string;
    clear_errors?: boolean;
    reason?: string;
  }): Promise<{ success: boolean; previous_phase: string; new_phase: string }> {
    return this.http.post('/api/admin/nomic/reset', options);
  }

  async pause(reason?: string): Promise<{ success: boolean; status: string }> {
    return this.http.post('/api/admin/nomic/pause', { reason });
  }

  async resume(targetPhase?: string): Promise<{ success: boolean; phase: string }> {
    return this.http.post('/api/admin/nomic/resume', { target_phase: targetPhase });
  }

  async resetCircuitBreakers(): Promise<{ success: boolean; previously_open: string[] }> {
    return this.http.post('/api/admin/nomic/circuit-breakers/reset', {});
  }
}

// =============================================================================
// Genesis API (Genetic Evolution)
// =============================================================================

export interface GenesisStats {
  total_genomes: number;
  active_genomes: number;
  total_debates: number;
  average_fitness: number;
  top_fitness: number;
}

export interface GenesisEvent {
  event_type: string;
  genome_id: string;
  timestamp: string;
  details: Record<string, unknown>;
}

export interface Genome {
  genome_id: string;
  fitness: number;
  generation: number;
  parent_ids?: string[];
  traits: Record<string, unknown>;
  created_at: string;
  debates_count: number;
}

export interface GenesisLineage {
  genome_id: string;
  ancestors: Genome[];
  descendants: Genome[];
  depth: number;
}

export interface GenesisTree {
  debate_id: string;
  nodes: Array<{ id: string; genome_id: string; parent_id?: string; fitness: number }>;
}

class GenesisAPI {
  constructor(private http: HttpClient) {}

  async stats(): Promise<{ stats: GenesisStats }> {
    return this.http.get('/api/genesis/stats');
  }

  async events(limit = 20): Promise<{ events: GenesisEvent[] }> {
    return this.http.get(`/api/genesis/events?limit=${limit}`);
  }

  async genomes(params?: { limit?: number; offset?: number }): Promise<{ genomes: Genome[] }> {
    const query = new URLSearchParams();
    if (params?.limit) query.set('limit', params.limit.toString());
    if (params?.offset) query.set('offset', params.offset.toString());
    return this.http.get(`/api/genesis/genomes?${query}`);
  }

  async topGenomes(limit = 10): Promise<{ genomes: Genome[] }> {
    return this.http.get(`/api/genesis/genomes/top?limit=${limit}`);
  }

  async population(): Promise<{ population: Genome[]; generation: number }> {
    return this.http.get('/api/genesis/population');
  }

  async genome(genomeId: string): Promise<{ genome: Genome }> {
    return this.http.get(`/api/genesis/genomes/${genomeId}`);
  }

  async lineage(genomeId: string): Promise<{ lineage: GenesisLineage }> {
    return this.http.get(`/api/genesis/lineage/${genomeId}`);
  }

  async tree(debateId: string): Promise<{ tree: GenesisTree }> {
    return this.http.get(`/api/genesis/tree/${debateId}`);
  }
}

// =============================================================================
// Gauntlet API (Stress Testing)
// =============================================================================

export interface GauntletPersona {
  id: string;
  name: string;
  description: string;
  traits: string[];
  difficulty: 'easy' | 'medium' | 'hard' | 'extreme';
}

export interface GauntletRunRequest {
  decision: string;
  personas?: string[];
  rounds?: number;
  stress_level?: number;
}

export interface GauntletResult {
  gauntlet_id: string;
  decision: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  personas_used: string[];
  rounds_completed: number;
  risk_score: number;
  vulnerabilities: Array<{ category: string; severity: string; description: string }>;
  recommendation: string;
  created_at: string;
  completed_at?: string;
}

export interface GauntletReceipt {
  gauntlet_id: string;
  decision?: string;
  input_summary?: string;
  verdict: 'approved' | 'rejected' | 'needs_review' | 'PASS' | 'CONDITIONAL' | 'FAIL' | string;
  confidence: number;
  risk_factors?: Array<{ factor: string; weight: number; assessment: string }>;
  signatures?: string[];
  agent_responses?: Array<{
    agent: string;
    response: string;
    role?: string;
    round?: number;
    provider?: string;
    provider_display?: string;
    model?: string;
    llm_label?: string;
  }>;
}

export interface GauntletHeatmap {
  gauntlet_id: string;
  categories: string[];
  data: number[][];
  max_risk: number;
}

export interface GauntletComparison {
  gauntlet_a: GauntletResult;
  gauntlet_b: GauntletResult;
  differences: Array<{ aspect: string; a_value: unknown; b_value: unknown }>;
  recommendation: string;
}

class GauntletAPI {
  constructor(private http: HttpClient) {}

  async run(request: GauntletRunRequest): Promise<{ gauntlet_id: string; status: string }> {
    return this.http.post('/api/gauntlet/run', request);
  }

  async personas(): Promise<{ personas: GauntletPersona[] }> {
    return this.http.get('/api/gauntlet/personas');
  }

  async results(params?: {
    limit?: number;
    offset?: number;
  }): Promise<{ results: GauntletResult[] }> {
    const query = new URLSearchParams();
    if (params?.limit) query.set('limit', params.limit.toString());
    if (params?.offset) query.set('offset', params.offset.toString());
    return this.http.get(`/api/gauntlet/results?${query}`);
  }

  async get(gauntletId: string): Promise<{ gauntlet: GauntletResult }> {
    return this.http.get(`/api/gauntlet/${gauntletId}`);
  }

  async receipt(gauntletId: string): Promise<{ receipt: GauntletReceipt }> {
    return this.http.get(`/api/gauntlet/${gauntletId}/receipt`);
  }

  async heatmap(gauntletId: string): Promise<{ heatmap: GauntletHeatmap }> {
    return this.http.get(`/api/gauntlet/${gauntletId}/heatmap`);
  }

  async compare(
    gauntletIdA: string,
    gauntletIdB: string,
  ): Promise<{ comparison: GauntletComparison }> {
    return this.http.get(`/api/gauntlet/${gauntletIdA}/compare/${gauntletIdB}`);
  }

  async delete(gauntletId: string): Promise<{ success: boolean }> {
    return this.http.delete(`/api/gauntlet/${gauntletId}`);
  }
}

// =============================================================================
// Documents API (Document Management & Auditing)
// =============================================================================

export type DocumentStatus = 'pending' | 'processing' | 'completed' | 'failed';
export type AuditType = 'security' | 'compliance' | 'consistency' | 'quality';
export type FindingSeverity = 'critical' | 'high' | 'medium' | 'low' | 'info';
export type AuditSessionStatus =
  'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled';

export interface Document {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  status: DocumentStatus;
  chunk_count: number;
  created_at: string;
  metadata?: Record<string, unknown>;
}

export interface DocumentChunk {
  id: string;
  document_id: string;
  content: string;
  chunk_index: number;
  token_count: number;
  metadata?: Record<string, unknown>;
}

export interface DocumentUploadResponse {
  document_id: string;
  filename: string;
  status: DocumentStatus;
  message?: string;
}

export interface BatchUploadResponse {
  job_id: string;
  document_count: number;
  status: string;
  message?: string;
}

export interface BatchJobStatus {
  job_id: string;
  status: string;
  progress: number;
  document_count: number;
  completed_count: number;
  failed_count: number;
  error?: string;
  created_at: string;
  updated_at?: string;
}

export interface BatchJobResults {
  job_id: string;
  documents: Document[];
  failed: Array<{ filename: string; error: string }>;
}

export interface DocumentContext {
  document_id: string;
  total_tokens: number;
  context: string;
  chunks_used: number;
  truncated: boolean;
}

export interface ProcessingStats {
  total_documents: number;
  pending: number;
  processing: number;
  completed: number;
  failed: number;
  total_chunks: number;
  total_tokens: number;
}

export interface SupportedFormats {
  formats: string[];
  mime_types: string[];
}

export interface AuditFinding {
  id: string;
  session_id: string;
  document_id: string;
  chunk_id?: string;
  audit_type: AuditType;
  category: string;
  severity: FindingSeverity;
  confidence: number;
  title: string;
  description: string;
  evidence_text?: string;
  evidence_location?: string;
  recommendation?: string;
  found_by?: string;
  created_at?: string;
}

export interface AuditSession {
  id: string;
  document_ids: string[];
  audit_types: AuditType[];
  status: AuditSessionStatus;
  progress: number;
  finding_count: number;
  model: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
}

export interface AuditSessionCreateResponse {
  session_id: string;
  status: AuditSessionStatus;
  document_count: number;
  audit_types: string[];
}

export interface AuditReport {
  session_id: string;
  format: 'json' | 'markdown' | 'html' | 'pdf';
  content: string;
  generated_at: string;
}

class DocumentsAPI {
  constructor(private http: HttpClient) {}

  // Document Management

  async list(options?: {
    limit?: number;
    offset?: number;
    status?: DocumentStatus;
  }): Promise<{ documents: Document[] }> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    if (options?.status) params.set('status', options.status);
    const query = params.toString();
    return this.http.get(`/api/documents${query ? `?${query}` : ''}`);
  }

  async get(documentId: string): Promise<Document> {
    return this.http.get(`/api/documents/${documentId}`);
  }

  async upload(file: File, metadata?: Record<string, unknown>): Promise<DocumentUploadResponse> {
    const content = await this.fileToBase64(file);
    return this.http.post('/api/documents/upload', {
      filename: file.name,
      content,
      content_type: file.type || 'application/octet-stream',
      metadata,
    });
  }

  async delete(documentId: string): Promise<{ success: boolean }> {
    return this.http.delete(`/api/documents/${documentId}`);
  }

  async formats(): Promise<SupportedFormats> {
    return this.http.get('/api/documents/formats');
  }

  // Batch Processing

  async batchUpload(
    files: File[],
    metadata?: Record<string, unknown>,
  ): Promise<BatchUploadResponse> {
    const fileData = await Promise.all(
      files.map(async (file) => ({
        filename: file.name,
        content: await this.fileToBase64(file),
        content_type: file.type || 'application/octet-stream',
      })),
    );
    return this.http.post('/api/documents/batch', { files: fileData, metadata });
  }

  async batchStatus(jobId: string): Promise<BatchJobStatus> {
    return this.http.get(`/api/documents/batch/${jobId}`);
  }

  async batchResults(jobId: string): Promise<BatchJobResults> {
    return this.http.get(`/api/documents/batch/${jobId}/results`);
  }

  async batchCancel(jobId: string): Promise<{ success: boolean }> {
    return this.http.delete(`/api/documents/batch/${jobId}`);
  }

  async processingStats(): Promise<ProcessingStats> {
    return this.http.get('/api/documents/processing/stats');
  }

  // Document Content

  async chunks(
    documentId: string,
    options?: { limit?: number; offset?: number },
  ): Promise<{ chunks: DocumentChunk[] }> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    const query = params.toString();
    return this.http.get(`/api/documents/${documentId}/chunks${query ? `?${query}` : ''}`);
  }

  async context(
    documentId: string,
    options?: { max_tokens?: number; model?: string },
  ): Promise<DocumentContext> {
    const params = new URLSearchParams();
    if (options?.max_tokens) params.set('max_tokens', String(options.max_tokens));
    if (options?.model) params.set('model', options.model);
    const query = params.toString();
    return this.http.get(`/api/documents/${documentId}/context${query ? `?${query}` : ''}`);
  }

  // Audit Sessions

  async createAudit(options: {
    document_ids: string[];
    audit_types?: AuditType[];
    model?: string;
  }): Promise<AuditSessionCreateResponse> {
    return this.http.post('/api/audit/sessions', {
      document_ids: options.document_ids,
      audit_types: options.audit_types || ['security', 'compliance', 'consistency', 'quality'],
      model: options.model || 'gemini-1.5-flash',
    });
  }

  async listAudits(options?: {
    limit?: number;
    offset?: number;
    status?: AuditSessionStatus;
  }): Promise<{ sessions: AuditSession[] }> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    if (options?.status) params.set('status', options.status);
    const query = params.toString();
    return this.http.get(`/api/audit/sessions${query ? `?${query}` : ''}`);
  }

  async getAudit(sessionId: string): Promise<AuditSession> {
    return this.http.get(`/api/audit/sessions/${sessionId}`);
  }

  async startAudit(sessionId: string): Promise<AuditSession> {
    return this.http.post(`/api/audit/sessions/${sessionId}/start`, {});
  }

  async pauseAudit(sessionId: string): Promise<AuditSession> {
    return this.http.post(`/api/audit/sessions/${sessionId}/pause`, {});
  }

  async resumeAudit(sessionId: string): Promise<AuditSession> {
    return this.http.post(`/api/audit/sessions/${sessionId}/resume`, {});
  }

  async cancelAudit(sessionId: string): Promise<AuditSession> {
    return this.http.post(`/api/audit/sessions/${sessionId}/cancel`, {});
  }

  async auditFindings(
    sessionId: string,
    options?: { severity?: FindingSeverity; audit_type?: AuditType },
  ): Promise<{ findings: AuditFinding[] }> {
    const params = new URLSearchParams();
    if (options?.severity) params.set('severity', options.severity);
    if (options?.audit_type) params.set('audit_type', options.audit_type);
    const query = params.toString();
    return this.http.get(`/api/audit/sessions/${sessionId}/findings${query ? `?${query}` : ''}`);
  }

  async auditReport(
    sessionId: string,
    format: 'json' | 'markdown' | 'html' | 'pdf' = 'json',
  ): Promise<AuditReport> {
    return this.http.get(`/api/audit/sessions/${sessionId}/report?format=${format}`);
  }

  async intervene(sessionId: string, action: string, message?: string): Promise<AuditSession> {
    return this.http.post(`/api/audit/sessions/${sessionId}/intervene`, { action, message });
  }

  // Helper Methods

  private async fileToBase64(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result as string;
        // Remove data URL prefix (e.g., "data:application/pdf;base64,")
        const base64 = result.split(',')[1] || result;
        resolve(base64);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }
}

// =============================================================================
// Control Plane API
// =============================================================================

export type ControlPlaneAgentStatus =
  'starting' | 'available' | 'busy' | 'draining' | 'offline' | 'failed';

export interface ControlPlaneAgent {
  agent_id: string;
  capabilities: string[];
  model: string;
  provider: string;
  status: ControlPlaneAgentStatus;
  metadata?: Record<string, unknown>;
  tasks_completed?: number;
  tasks_failed?: number;
  avg_latency_ms?: number;
  last_heartbeat?: string;
  registered_at?: string;
}

export interface ControlPlaneTask {
  id: string;
  name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  assigned_agent?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
}

export interface ControlPlaneHealth {
  status: 'healthy' | 'degraded' | 'unhealthy';
  agents: Record<
    string,
    {
      agent_id: string;
      status: 'healthy' | 'degraded' | 'unhealthy';
      last_heartbeat?: string;
      latency_ms?: number;
      error_rate?: number;
    }
  >;
  agents_available?: number;
  agents_total?: number;
  active_tasks?: number;
  uptime_seconds?: number;
  timestamp?: string;
}

class ControlPlaneAPI {
  constructor(private http: HttpClient) {}

  async listAgents(): Promise<{ agents: ControlPlaneAgent[] }> {
    return this.http.get('/api/control-plane/agents');
  }

  async getAgent(agentId: string): Promise<{ agent: ControlPlaneAgent }> {
    return this.http.get(`/api/control-plane/agents/${agentId}`);
  }

  async listTasks(): Promise<{ tasks: ControlPlaneTask[] }> {
    return this.http.get('/api/control-plane/tasks');
  }

  async getTask(taskId: string): Promise<{ task: ControlPlaneTask }> {
    return this.http.get(`/api/control-plane/tasks/${taskId}`);
  }

  async createTask(task: { name: string; agent_id?: string }): Promise<{ task: ControlPlaneTask }> {
    return this.http.post('/api/control-plane/tasks', task);
  }

  async cancelTask(taskId: string): Promise<{ success: boolean }> {
    return this.http.post(`/api/control-plane/tasks/${taskId}/cancel`, {});
  }

  async health(): Promise<{ health: ControlPlaneHealth }> {
    return this.http.get('/api/control-plane/health');
  }
}

// =============================================================================
// Policy API (Compliance & Policy Management)
// =============================================================================

export type PolicyLevel = 'required' | 'recommended' | 'optional';
export type ViolationStatus = 'open' | 'investigating' | 'resolved' | 'false_positive';
export type ViolationSeverity = 'critical' | 'high' | 'medium' | 'low' | 'info';

export interface PolicyRule {
  id: string;
  name: string;
  description: string;
  pattern?: string;
  severity: ViolationSeverity;
  enabled: boolean;
}

export interface Policy {
  id: string;
  name: string;
  description: string;
  framework_id: string;
  workspace_id: string;
  vertical_id: string;
  level: PolicyLevel;
  enabled: boolean;
  rules: PolicyRule[];
  metadata?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export interface PolicyInput {
  name: string;
  description?: string;
  framework_id: string;
  workspace_id?: string;
  vertical_id: string;
  level?: PolicyLevel;
  enabled?: boolean;
  rules?: Omit<PolicyRule, 'id'>[];
  metadata?: Record<string, unknown>;
}

export interface Violation {
  id: string;
  policy_id: string;
  rule_id: string;
  rule_name: string;
  framework_id: string;
  vertical_id: string;
  workspace_id: string;
  severity: ViolationSeverity;
  status: ViolationStatus;
  description: string;
  source: string;
  resolved_by?: string;
  resolved_at?: string;
  resolution_notes?: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
}

export interface ViolationFilters {
  workspace_id?: string;
  vertical_id?: string;
  framework_id?: string;
  policy_id?: string;
  status?: ViolationStatus;
  severity?: ViolationSeverity;
  limit?: number;
  offset?: number;
}

export interface ComplianceCheckResult {
  compliant: boolean;
  score: number;
  issues: Array<{
    rule_id: string;
    framework: string;
    severity: ViolationSeverity;
    description: string;
    metadata?: Record<string, unknown>;
  }>;
}

export interface ComplianceStats {
  policies: { total: number; enabled: number; disabled: number };
  violations: {
    total: number;
    open: number;
    by_severity: { critical: number; high: number; medium: number; low: number };
  };
  risk_score: number;
}

class PolicyAPI {
  constructor(private http: HttpClient) {}

  async list(options?: {
    workspace_id?: string;
    vertical_id?: string;
    framework_id?: string;
    enabled_only?: boolean;
    limit?: number;
    offset?: number;
  }): Promise<{ policies: Policy[]; total: number }> {
    const params = new URLSearchParams();
    if (options?.workspace_id) params.set('workspace_id', options.workspace_id);
    if (options?.vertical_id) params.set('vertical_id', options.vertical_id);
    if (options?.framework_id) params.set('framework_id', options.framework_id);
    if (options?.enabled_only) params.set('enabled_only', 'true');
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    const query = params.toString();
    return this.http.get(`/api/policies${query ? `?${query}` : ''}`);
  }

  async get(policyId: string): Promise<{ policy: Policy }> {
    return this.http.get(`/api/policies/${policyId}`);
  }

  async create(policy: PolicyInput): Promise<{ policy: Policy; message: string }> {
    return this.http.post('/api/policies', policy);
  }

  async update(
    policyId: string,
    updates: Partial<PolicyInput>,
  ): Promise<{ policy: Policy; message: string }> {
    return this.http.put(`/api/policies/${policyId}`, updates);
  }

  async delete(policyId: string): Promise<{ message: string; policy_id: string }> {
    return this.http.delete(`/api/policies/${policyId}`);
  }

  async toggle(
    policyId: string,
    enabled?: boolean,
  ): Promise<{ message: string; policy_id: string; enabled: boolean }> {
    return this.http.post(`/api/policies/${policyId}/toggle`, { enabled });
  }

  async getViolations(
    policyId: string,
    options?: {
      status?: ViolationStatus;
      severity?: ViolationSeverity;
      limit?: number;
      offset?: number;
    },
  ): Promise<{ violations: Violation[]; total: number; policy_id: string }> {
    const params = new URLSearchParams();
    if (options?.status) params.set('status', options.status);
    if (options?.severity) params.set('severity', options.severity);
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    const query = params.toString();
    return this.http.get(`/api/policies/${policyId}/violations${query ? `?${query}` : ''}`);
  }

  async listViolations(
    filters?: ViolationFilters,
  ): Promise<{ violations: Violation[]; total: number }> {
    const params = new URLSearchParams();
    if (filters?.workspace_id) params.set('workspace_id', filters.workspace_id);
    if (filters?.vertical_id) params.set('vertical_id', filters.vertical_id);
    if (filters?.framework_id) params.set('framework_id', filters.framework_id);
    if (filters?.policy_id) params.set('policy_id', filters.policy_id);
    if (filters?.status) params.set('status', filters.status);
    if (filters?.severity) params.set('severity', filters.severity);
    if (filters?.limit) params.set('limit', String(filters.limit));
    if (filters?.offset) params.set('offset', String(filters.offset));
    const query = params.toString();
    return this.http.get(`/api/compliance/violations${query ? `?${query}` : ''}`);
  }

  async getViolation(violationId: string): Promise<{ violation: Violation }> {
    return this.http.get(`/api/compliance/violations/${violationId}`);
  }

  async updateViolation(
    violationId: string,
    status: ViolationStatus,
    notes?: string,
  ): Promise<{ violation: Violation; message: string }> {
    return this.http.put(`/api/compliance/violations/${violationId}`, {
      status,
      resolution_notes: notes,
    });
  }

  async checkCompliance(
    content: string,
    options?: {
      frameworks?: string[];
      min_severity?: ViolationSeverity;
      store_violations?: boolean;
      workspace_id?: string;
      source?: string;
    },
  ): Promise<{
    result: ComplianceCheckResult;
    compliant: boolean;
    score: number;
    issue_count: number;
  }> {
    return this.http.post('/api/compliance/check', { content, ...options });
  }

  async getStats(workspaceId?: string): Promise<ComplianceStats> {
    const params = workspaceId ? `?workspace_id=${workspaceId}` : '';
    return this.http.get(`/api/compliance/stats${params}`);
  }
}

// =============================================================================
// Workflows API (Visual Workflow Builder)
// =============================================================================

export type WorkflowStatus = 'draft' | 'active' | 'archived';
export type WorkflowCategory =
  'general' | 'legal' | 'healthcare' | 'finance' | 'research' | 'custom';
export type ExecutionStatus = 'pending' | 'running' | 'completed' | 'failed' | 'terminated';

export interface WorkflowStep {
  id: string;
  name: string;
  step_type: 'agent' | 'debate' | 'decision' | 'human_checkpoint' | 'condition' | 'parallel';
  config: Record<string, unknown>;
  description?: string;
  next_steps?: string[];
  visual?: { position: { x: number; y: number }; category: string; color?: string };
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  category: WorkflowCategory;
  tags: string[];
  version: string;
  status: WorkflowStatus;
  steps: WorkflowStep[];
  is_template: boolean;
  tenant_id: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  metadata?: Record<string, unknown>;
}

export interface WorkflowInput {
  name: string;
  description?: string;
  category?: WorkflowCategory;
  tags?: string[];
  steps: Omit<WorkflowStep, 'id'>[];
  metadata?: Record<string, unknown>;
}

export interface WorkflowExecution {
  id: string;
  workflow_id: string;
  tenant_id: string;
  status: ExecutionStatus;
  started_at: string;
  completed_at?: string;
  inputs: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  steps?: Array<{
    step_id: string;
    status: string;
    started_at: string;
    completed_at?: string;
    output?: unknown;
    error?: string;
  }>;
  error?: string;
  duration_ms?: number;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  category: WorkflowCategory;
  tags: string[];
  icon?: string;
  usage_count: number;
  steps: WorkflowStep[];
}

export interface WorkflowVersion {
  version: string;
  created_at: string;
  created_by: string;
  changes?: string;
}

export interface WorkflowApproval {
  id: string;
  workflow_id: string;
  execution_id: string;
  step_id: string;
  status: 'pending' | 'approved' | 'rejected';
  requested_at: string;
  resolved_at?: string;
  responder_id?: string;
  notes?: string;
  context?: Record<string, unknown>;
}

class WorkflowsAPI {
  constructor(private http: HttpClient) {}

  async list(options?: {
    category?: WorkflowCategory;
    tags?: string[];
    search?: string;
    limit?: number;
    offset?: number;
  }): Promise<{ workflows: Workflow[]; total_count: number }> {
    const params = new URLSearchParams();
    if (options?.category) params.set('category', options.category);
    if (options?.tags) options.tags.forEach((t) => params.append('tags', t));
    if (options?.search) params.set('search', options.search);
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    const query = params.toString();
    return this.http.get(`/api/workflows${query ? `?${query}` : ''}`);
  }

  async get(workflowId: string): Promise<Workflow> {
    return this.http.get(`/api/workflows/${workflowId}`);
  }

  async create(workflow: WorkflowInput): Promise<Workflow> {
    return this.http.post('/api/workflows', workflow);
  }

  async update(workflowId: string, workflow: Partial<WorkflowInput>): Promise<Workflow> {
    return this.http.put(`/api/workflows/${workflowId}`, workflow);
  }

  async delete(workflowId: string): Promise<{ success: boolean }> {
    return this.http.delete(`/api/workflows/${workflowId}`);
  }

  async execute(workflowId: string, inputs?: Record<string, unknown>): Promise<WorkflowExecution> {
    return this.http.post(`/api/workflows/${workflowId}/execute`, { inputs });
  }

  async simulate(
    workflowId: string,
    inputs?: Record<string, unknown>,
  ): Promise<{ valid: boolean; errors: string[]; estimated_duration_ms?: number }> {
    return this.http.post(`/api/workflows/${workflowId}/simulate`, { inputs });
  }

  async getExecution(executionId: string): Promise<WorkflowExecution> {
    return this.http.get(`/api/workflows/executions/${executionId}`);
  }

  async listExecutions(workflowId?: string, limit = 20): Promise<WorkflowExecution[]> {
    const params = new URLSearchParams();
    if (workflowId) params.set('workflow_id', workflowId);
    params.set('limit', String(limit));
    const query = params.toString();
    return this.http.get(`/api/workflows/executions${query ? `?${query}` : ''}`);
  }

  async cancelExecution(executionId: string): Promise<{ success: boolean }> {
    return this.http.post(`/api/workflows/executions/${executionId}/terminate`, {});
  }

  async getVersions(workflowId: string, limit = 20): Promise<WorkflowVersion[]> {
    return this.http.get(`/api/workflows/${workflowId}/versions?limit=${limit}`);
  }

  async restoreVersion(workflowId: string, version: string): Promise<Workflow> {
    return this.http.post(`/api/workflows/${workflowId}/restore`, { version });
  }

  async listTemplates(options?: {
    category?: WorkflowCategory;
    tags?: string[];
  }): Promise<WorkflowTemplate[]> {
    const params = new URLSearchParams();
    if (options?.category) params.set('category', options.category);
    if (options?.tags) options.tags.forEach((t) => params.append('tags', t));
    const query = params.toString();
    return this.http.get(`/api/workflow-templates${query ? `?${query}` : ''}`);
  }

  async getTemplate(templateId: string): Promise<WorkflowTemplate> {
    return this.http.get(`/api/workflow-templates/${templateId}`);
  }

  async createFromTemplate(
    templateId: string,
    name: string,
    customizations?: Record<string, unknown>,
  ): Promise<Workflow> {
    return this.http.post('/api/workflows/from-template', {
      template_id: templateId,
      name,
      customizations,
    });
  }

  async listApprovals(workflowId?: string): Promise<WorkflowApproval[]> {
    const params = workflowId ? `?workflow_id=${workflowId}` : '';
    return this.http.get(`/api/workflow-approvals${params}`);
  }

  async resolveApproval(
    requestId: string,
    status: 'approved' | 'rejected',
    notes?: string,
  ): Promise<{ success: boolean }> {
    return this.http.post(`/api/workflow-approvals/${requestId}/resolve`, { status, notes });
  }
}

// =============================================================================
// Connectors API (Enterprise Data Connectors)
// =============================================================================

export type ConnectorType =
  | 'mongodb'
  | 'postgresql'
  | 'mysql'
  | 's3'
  | 'google_drive'
  | 'sharepoint'
  | 'slack'
  | 'notion'
  | 'confluence'
  | 'fhir'
  | 'custom';

export type ConnectorStatus = 'active' | 'inactive' | 'error' | 'syncing';
export type SyncJobStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface Connector {
  id: string;
  name: string;
  connector_type: ConnectorType;
  status: ConnectorStatus;
  workspace_id: string;
  config: Record<string, unknown>;
  credentials_set: boolean;
  last_sync_at?: string;
  last_sync_status?: SyncJobStatus;
  document_count: number;
  error_message?: string;
  created_at: string;
  updated_at: string;
  metadata?: Record<string, unknown>;
}

export interface ConnectorInput {
  name: string;
  connector_type: ConnectorType;
  workspace_id?: string;
  config: Record<string, unknown>;
  credentials?: Record<string, string>;
  metadata?: Record<string, unknown>;
}

export interface SyncJob {
  id: string;
  connector_id: string;
  status: SyncJobStatus;
  started_at: string;
  completed_at?: string;
  documents_processed: number;
  documents_added: number;
  documents_updated: number;
  documents_deleted: number;
  error_message?: string;
  progress_percent: number;
}

export interface SyncHistory {
  syncs: SyncJob[];
  total: number;
}

export interface ConnectorStats {
  total_connectors: number;
  active_connectors: number;
  total_documents: number;
  syncs_today: number;
  syncs_failed_today: number;
  by_type: Record<ConnectorType, number>;
}

export interface ConnectionTestResult {
  success: boolean;
  message: string;
  latency_ms?: number;
  details?: Record<string, unknown>;
}

class ConnectorsAPI {
  constructor(private http: HttpClient) {}

  async list(options?: {
    workspace_id?: string;
    connector_type?: ConnectorType;
    status?: ConnectorStatus;
    limit?: number;
    offset?: number;
  }): Promise<{ connectors: Connector[]; total: number }> {
    const params = new URLSearchParams();
    if (options?.workspace_id) params.set('workspace_id', options.workspace_id);
    if (options?.connector_type) params.set('connector_type', options.connector_type);
    if (options?.status) params.set('status', options.status);
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    const query = params.toString();
    return this.http.get(`/api/connectors${query ? `?${query}` : ''}`);
  }

  async get(connectorId: string): Promise<{ connector: Connector }> {
    return this.http.get(`/api/connectors/${connectorId}`);
  }

  async create(connector: ConnectorInput): Promise<{ connector: Connector; message: string }> {
    return this.http.post('/api/connectors', connector);
  }

  async update(
    connectorId: string,
    updates: Partial<ConnectorInput>,
  ): Promise<{ connector: Connector; message: string }> {
    return this.http.put(`/api/connectors/${connectorId}`, updates);
  }

  async delete(connectorId: string): Promise<{ success: boolean; message: string }> {
    return this.http.delete(`/api/connectors/${connectorId}`);
  }

  async sync(
    connectorId: string,
    options?: { full_sync?: boolean; filters?: Record<string, unknown> },
  ): Promise<{ sync_job: SyncJob }> {
    return this.http.post(`/api/connectors/${connectorId}/sync`, options || {});
  }

  async cancelSync(syncId: string): Promise<{ success: boolean; message: string }> {
    return this.http.post(`/api/connectors/sync/${syncId}/cancel`, {});
  }

  async getSyncStatus(syncId: string): Promise<{ sync_job: SyncJob }> {
    return this.http.get(`/api/connectors/sync/${syncId}`);
  }

  async getSyncHistory(options?: {
    connector_id?: string;
    status?: SyncJobStatus;
    limit?: number;
    offset?: number;
  }): Promise<SyncHistory> {
    const params = new URLSearchParams();
    if (options?.connector_id) params.set('connector_id', options.connector_id);
    if (options?.status) params.set('status', options.status);
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    const query = params.toString();
    return this.http.get(`/api/connectors/sync-history${query ? `?${query}` : ''}`);
  }

  async testConnection(
    connectorType: ConnectorType,
    config: Record<string, unknown>,
    credentials?: Record<string, string>,
  ): Promise<ConnectionTestResult> {
    return this.http.post('/api/connectors/test', {
      connector_type: connectorType,
      config,
      credentials,
    });
  }

  async getStats(workspaceId?: string): Promise<{ stats: ConnectorStats }> {
    const params = workspaceId ? `?workspace_id=${workspaceId}` : '';
    return this.http.get(`/api/connectors/stats${params}`);
  }

  async listTypes(): Promise<{
    types: Array<{ type: ConnectorType; name: string; description: string; config_schema: object }>;
  }> {
    return this.http.get('/api/connectors/types');
  }
}

// =============================================================================
// Repositories API (Code Repository Indexing)
// =============================================================================

export type IndexJobStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface CodeEntity {
  id: string;
  repository_id: string;
  file_path: string;
  entity_type: 'class' | 'function' | 'method' | 'interface' | 'constant' | 'module';
  name: string;
  signature?: string;
  docstring?: string;
  start_line: number;
  end_line: number;
  language: string;
  metadata?: Record<string, unknown>;
}

export interface RelationshipGraph {
  nodes: Array<{ id: string; name: string; type: string; file_path: string }>;
  edges: Array<{
    source: string;
    target: string;
    relationship: 'imports' | 'calls' | 'inherits' | 'implements' | 'references';
  }>;
}

export interface IndexJob {
  id: string;
  repository_path: string;
  status: IndexJobStatus;
  started_at: string;
  completed_at?: string;
  files_processed: number;
  files_total: number;
  entities_found: number;
  relationships_found: number;
  error_message?: string;
  progress_percent: number;
}

export interface IndexOptions {
  languages?: string[];
  exclude_patterns?: string[];
  include_patterns?: string[];
  max_file_size_kb?: number;
  extract_relationships?: boolean;
}

class RepositoriesAPI {
  constructor(private http: HttpClient) {}

  async index(repoPath: string, options?: IndexOptions): Promise<{ job: IndexJob }> {
    return this.http.post('/api/repository/index', { repo_path: repoPath, ...options });
  }

  async incrementalUpdate(repositoryId: string): Promise<{ job: IndexJob }> {
    return this.http.post(`/api/repository/${repositoryId}/incremental`, {});
  }

  async getIndexStatus(jobId: string): Promise<{ job: IndexJob }> {
    return this.http.get(`/api/repository/jobs/${jobId}`);
  }

  async getEntities(
    repositoryId: string,
    options?: {
      entity_type?: string;
      file_path?: string;
      search?: string;
      limit?: number;
      offset?: number;
    },
  ): Promise<{ entities: CodeEntity[]; total: number }> {
    const params = new URLSearchParams();
    if (options?.entity_type) params.set('entity_type', options.entity_type);
    if (options?.file_path) params.set('file_path', options.file_path);
    if (options?.search) params.set('search', options.search);
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    const query = params.toString();
    return this.http.get(`/api/repository/${repositoryId}/entities${query ? `?${query}` : ''}`);
  }

  async getRelationshipGraph(
    repositoryId: string,
    options?: { root_entity?: string; depth?: number; relationship_types?: string[] },
  ): Promise<{ graph: RelationshipGraph }> {
    const params = new URLSearchParams();
    if (options?.root_entity) params.set('root_entity', options.root_entity);
    if (options?.depth) params.set('depth', String(options.depth));
    if (options?.relationship_types)
      options.relationship_types.forEach((t) => params.append('relationship_types', t));
    const query = params.toString();
    return this.http.get(`/api/repository/${repositoryId}/graph${query ? `?${query}` : ''}`);
  }

  async delete(repositoryId: string): Promise<{ success: boolean }> {
    return this.http.delete(`/api/repository/${repositoryId}`);
  }

  async list(options?: {
    limit?: number;
    offset?: number;
  }): Promise<{
    repositories: Array<{ id: string; path: string; indexed_at: string; entity_count: number }>;
    total: number;
  }> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    const query = params.toString();
    return this.http.get(`/api/repository${query ? `?${query}` : ''}`);
  }
}

// =============================================================================
// Queue API (Job Queue Management)
// =============================================================================

export type QueueJobStatus =
  'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'retrying';
export type QueueJobPriority = 'low' | 'normal' | 'high' | 'critical';

export interface QueueJob {
  id: string;
  job_type: string;
  status: QueueJobStatus;
  priority: QueueJobPriority;
  payload: Record<string, unknown>;
  result?: Record<string, unknown>;
  error_message?: string;
  attempt_count: number;
  max_attempts: number;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  scheduled_at?: string;
  worker_id?: string;
  metadata?: Record<string, unknown>;
}

export interface QueueJobInput {
  job_type: string;
  payload: Record<string, unknown>;
  priority?: QueueJobPriority;
  scheduled_at?: string;
  max_attempts?: number;
  metadata?: Record<string, unknown>;
}

export interface QueueStats {
  total_jobs: number;
  pending: number;
  running: number;
  completed: number;
  failed: number;
  jobs_per_minute: number;
  avg_processing_time_ms: number;
  by_type: Record<string, { total: number; pending: number; failed: number }>;
  workers_active: number;
}

class QueueAPI {
  constructor(private http: HttpClient) {}

  async listJobs(options?: {
    status?: QueueJobStatus;
    job_type?: string;
    priority?: QueueJobPriority;
    limit?: number;
    offset?: number;
  }): Promise<{ jobs: QueueJob[]; total: number }> {
    const params = new URLSearchParams();
    if (options?.status) params.set('status', options.status);
    if (options?.job_type) params.set('job_type', options.job_type);
    if (options?.priority) params.set('priority', options.priority);
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    const query = params.toString();
    return this.http.get(`/api/queue/jobs${query ? `?${query}` : ''}`);
  }

  async getJob(jobId: string): Promise<{ job: QueueJob }> {
    return this.http.get(`/api/queue/jobs/${jobId}`);
  }

  async submitJob(job: QueueJobInput): Promise<{ job: QueueJob }> {
    return this.http.post('/api/queue/jobs', job);
  }

  async cancelJob(jobId: string): Promise<{ success: boolean; message: string }> {
    return this.http.post(`/api/queue/jobs/${jobId}/cancel`, {});
  }

  async retryJob(jobId: string): Promise<{ job: QueueJob }> {
    return this.http.post(`/api/queue/jobs/${jobId}/retry`, {});
  }

  async getStats(): Promise<{ stats: QueueStats; timestamp: string }> {
    return this.http.get('/api/queue/stats');
  }

  async getWorkers(): Promise<{
    workers: Array<{ name: string; pending: number; idle_time_ms: number; last_delivery?: string }>;
    total: number;
  }> {
    return this.http.get('/api/queue/workers');
  }

  async purgeCompleted(olderThanHours = 24): Promise<{ purged_count: number }> {
    return this.http.post('/api/queue/purge', { older_than_hours: olderThanHours });
  }
}

// =============================================================================
// Extended Training API Types (Job Management)
// =============================================================================

export type TrainingJobStatus =
  'pending' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
export type TrainingJobType = 'sft' | 'dpo' | 'rlhf' | 'evaluation';

export interface TrainingJob {
  id: string;
  name: string;
  job_type: TrainingJobType;
  status: TrainingJobStatus;
  model_base: string;
  dataset_config: { source: string; filters?: Record<string, unknown>; sample_count: number };
  training_config: {
    epochs: number;
    batch_size: number;
    learning_rate: number;
    warmup_steps: number;
    [key: string]: unknown;
  };
  progress: number;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  metrics?: TrainingJobMetrics;
  artifacts?: TrainingJobArtifacts;
  metadata?: Record<string, unknown>;
}

export interface TrainingJobMetrics {
  loss: number[];
  eval_loss?: number[];
  accuracy?: number[];
  learning_rate?: number[];
  epoch: number;
  step: number;
  samples_processed: number;
  tokens_processed: number;
  training_time_seconds: number;
}

export interface TrainingJobArtifacts {
  model_path?: string;
  checkpoint_paths: string[];
  log_path?: string;
  config_path?: string;
  evaluation_report_path?: string;
}

export interface TrainingJobConfig {
  name: string;
  job_type: TrainingJobType;
  model_base: string;
  dataset_config: { source: string; filters?: Record<string, unknown>; sample_count?: number };
  training_config: {
    epochs?: number;
    batch_size?: number;
    learning_rate?: number;
    warmup_steps?: number;
    [key: string]: unknown;
  };
  metadata?: Record<string, unknown>;
}

// =============================================================================
// Main Client
// =============================================================================

export class AragoraClient {
  private http: HttpClient;

  readonly debates: DebatesAPI;
  readonly agents: AgentsAPI;
  readonly leaderboard: LeaderboardAPI;
  readonly organizations: OrganizationsAPI;
  /** User organizations API for multi-org support */
  readonly userOrganizations: UserOrganizationsAPI;
  readonly billing: BillingAPI;
  readonly analytics: AnalyticsAPI;
  readonly mfa: MFAAPI;
  readonly admin: AdminAPI;
  readonly system: SystemAPI;
  readonly training: TrainingAPI;
  readonly evidence: EvidenceAPI;
  // New APIs
  readonly tournaments: TournamentsAPI;
  readonly pulse: PulseAPI;
  readonly gallery: GalleryAPI;
  readonly moments: MomentsAPI;
  readonly agentDetail: AgentDetailAPI;
  readonly nomicAdmin: NomicAdminAPI;
  readonly genesis: GenesisAPI;
  readonly gauntlet: GauntletAPI;
  // Document Management & Auditing
  readonly documents: DocumentsAPI;
  // Control Plane
  readonly controlPlane: ControlPlaneAPI;
  // Enterprise APIs (Integration First)
  readonly policy: PolicyAPI;
  readonly workflows: WorkflowsAPI;
  readonly connectors: ConnectorsAPI;
  readonly repositories: RepositoriesAPI;
  readonly queue: QueueAPI;

  constructor(config: AragoraClientConfig) {
    this.http = new HttpClient(config);

    this.debates = new DebatesAPI(this.http);
    this.agents = new AgentsAPI(this.http);
    this.leaderboard = new LeaderboardAPI(this.http);
    this.organizations = new OrganizationsAPI(this.http);
    this.userOrganizations = new UserOrganizationsAPI(this.http);
    this.billing = new BillingAPI(this.http);
    this.analytics = new AnalyticsAPI(this.http);
    this.mfa = new MFAAPI(this.http);
    this.admin = new AdminAPI(this.http);
    this.system = new SystemAPI(this.http);
    this.training = new TrainingAPI(this.http);
    this.evidence = new EvidenceAPI(this.http);
    // New APIs
    this.tournaments = new TournamentsAPI(this.http);
    this.pulse = new PulseAPI(this.http);
    this.gallery = new GalleryAPI(this.http);
    this.moments = new MomentsAPI(this.http);
    this.agentDetail = new AgentDetailAPI(this.http);
    this.nomicAdmin = new NomicAdminAPI(this.http);
    this.genesis = new GenesisAPI(this.http);
    this.gauntlet = new GauntletAPI(this.http);
    // Document Management & Auditing
    this.documents = new DocumentsAPI(this.http);
    // Control Plane
    this.controlPlane = new ControlPlaneAPI(this.http);
    // Enterprise APIs (Integration First)
    this.policy = new PolicyAPI(this.http);
    this.workflows = new WorkflowsAPI(this.http);
    this.connectors = new ConnectorsAPI(this.http);
    this.repositories = new RepositoriesAPI(this.http);
    this.queue = new QueueAPI(this.http);
  }

  async health(): Promise<HealthStatus> {
    return this.system.health();
  }
}

// =============================================================================
// Export types for admin APIs
// =============================================================================

// Re-export internal types (not already exported with `export interface`)
export type {
  TierRevenue,
  RevenueResponse,
  AdminStatsResponse,
  AdminUsersResponse,
  AdminOrganizationsResponse,
  HealthStatus,
  CircuitBreakerState,
  RecentError,
  RateLimitState,
  TrainingExportOptions,
  DPOExportOptions,
  GauntletExportOptions,
  TrainingStatsResponse,
  TrainingFormatsResponse,
  TrainingExportResponse,
};

// =============================================================================
// Singleton and React Hook Integration
// =============================================================================

let clientInstance: AragoraClient | null = null;
let currentConfig: { baseUrl: string; apiKey?: string } | null = null;

/**
 * Get or create an AragoraClient instance.
 *
 * This creates a singleton client configured with the provided base URL and token.
 * If the configuration changes, a new client is created.
 *
 * @param token - Optional auth token (Bearer token)
 * @param baseUrl - API base URL (defaults to production)
 */
export function getClient(token?: string, baseUrl = 'https://api.aragora.ai'): AragoraClient {
  const newConfig = { baseUrl, apiKey: token };

  // Check if we need to create a new client
  if (
    !clientInstance ||
    !currentConfig ||
    currentConfig.baseUrl !== newConfig.baseUrl ||
    currentConfig.apiKey !== newConfig.apiKey
  ) {
    clientInstance = new AragoraClient(newConfig);
    currentConfig = newConfig;
  }

  return clientInstance;
}

/**
 * Clear the cached client instance.
 * Call this on logout to ensure fresh client on next login.
 */
export function clearClient(): void {
  clientInstance = null;
  currentConfig = null;
}
