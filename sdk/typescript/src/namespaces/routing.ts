/**
 * Routing Namespace API
 *
 * Provides intelligent routing and team selection:
 * - Best team composition recommendations
 * - Domain detection and auto-routing
 * - Configurable routing rules
 * - Rule evaluation and templates
 */

/**
 * Condition operator for routing rules.
 */
export type ConditionOperator =
  | 'eq'
  | 'neq'
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'contains'
  | 'not_contains'
  | 'starts_with'
  | 'ends_with'
  | 'matches'
  | 'in'
  | 'not_in'
  | 'exists'
  | 'not_exists';

/**
 * Action type for routing rules.
 */
export type ActionType =
  | 'route_to_channel'
  | 'route_to_agent'
  | 'escalate_to'
  | 'notify'
  | 'tag'
  | 'require_approval'
  | 'set_priority'
  | 'add_context'
  | 'transform'
  | 'reject';

/**
 * Match mode for multiple conditions.
 */
export type MatchMode = 'all' | 'any' | 'none';

/**
 * Agent recommendation.
 */
export interface AgentRecommendation {
  agent: string;
  score: number;
  domain_match: number;
  elo: number;
  calibration: number;
  reasoning: string;
}

/**
 * Team composition.
 */
export interface TeamComposition {
  agents: AgentRecommendation[];
  roles: Record<string, string>;
  expected_quality: number;
  diversity_score: number;
  rationale: string;
  estimated_rounds: number;
}

/**
 * Domain detection result.
 */
export interface DomainDetection {
  task: string;
  domains: Array<{
    domain: string;
    confidence: number;
    keywords: string[];
  }>;
  primary_domain: string;
  secondary_domains: string[];
}

/**
 * Domain leaderboard entry.
 */
export interface DomainLeaderboardEntry {
  agent: string;
  domain: string;
  elo: number;
  win_rate: number;
  debates_count: number;
  calibration_score: number;
  rank: number;
}

/**
 * Routing rule condition.
 */
export interface RuleCondition {
  field: string;
  operator: ConditionOperator;
  value: unknown;
  case_sensitive?: boolean;
}

/**
 * Routing rule action.
 */
export interface RuleAction {
  type: ActionType;
  target?: string;
  params?: Record<string, unknown>;
}

/**
 * Routing rule.
 */
export interface RoutingRule {
  id: string;
  name: string;
  description?: string;
  conditions: RuleCondition[];
  actions: RuleAction[];
  priority: number;
  enabled: boolean;
  match_mode: MatchMode;
  tags: string[];
  created_at: string;
  updated_at: string;
  created_by?: string;
}

/**
 * Rule evaluation result.
 */
export interface RuleEvaluationResult {
  rule_id: string;
  rule_name: string;
  matched: boolean;
  conditions_matched: number;
  conditions_total: number;
  actions: RuleAction[];
  execution_time_ms: number;
}

/**
 * Rule template.
 */
export interface RuleTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  conditions: RuleCondition[];
  actions: RuleAction[];
  variables: Array<{
    name: string;
    type: string;
    description: string;
    default?: unknown;
  }>;
}

/**
 * Best teams request options.
 */
export interface BestTeamsOptions {
  task?: string;
  domain?: string;
  min_agents?: number;
  max_agents?: number;
  required_agents?: string[];
  excluded_agents?: string[];
}

/**
 * Recommendations request.
 */
export interface RecommendationsRequest {
  task: string;
  context?: string;
  domain?: string;
  min_score?: number;
  max_results?: number;
}

/**
 * Auto-route request.
 */
export interface AutoRouteRequest {
  task: string;
  context?: Record<string, unknown>;
  source?: string;
  priority?: 'low' | 'normal' | 'high' | 'urgent';
}

/**
 * Auto-route response.
 */
export interface AutoRouteResponse {
  routed_to: string;
  team?: TeamComposition;
  domain: string;
  rules_applied: string[];
  confidence: number;
}

/**
 * Create rule request.
 */
export interface CreateRuleRequest {
  name: string;
  description?: string;
  conditions: RuleCondition[];
  actions: RuleAction[];
  priority?: number;
  enabled?: boolean;
  match_mode?: MatchMode;
  tags?: string[];
}

/**
 * Update rule request.
 */
export interface UpdateRuleRequest {
  name?: string;
  description?: string;
  conditions?: RuleCondition[];
  actions?: RuleAction[];
  priority?: number;
  match_mode?: MatchMode;
  tags?: string[];
}

/**
 * List rules options.
 */
export interface ListRulesOptions {
  enabled?: boolean;
  tag?: string;
  sort_by?: 'priority' | 'name' | 'created_at' | 'updated_at';
  sort_order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}

/**
 * Evaluate rules request.
 */
export interface EvaluateRulesRequest {
  context: Record<string, unknown>;
  rule_ids?: string[];
  stop_on_first_match?: boolean;
}

/**
 * Client interface for routing operations.
 */
interface RoutingClientInterface {
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }
  ): Promise<T>;
}

/**
 * Routing API namespace.
 *
 * Provides methods for intelligent routing and team selection:
 * - Get best team compositions
 * - Auto-route tasks to appropriate agents
 * - Manage routing rules
 * - Evaluate rules against context
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // Get best teams for a task
 * const { teams } = await client.routing.getBestTeams({
 *   task: 'Review legal contract',
 *   min_agents: 2,
 *   max_agents: 4,
 * });
 *
 * // Auto-route a task
 * const route = await client.routing.autoRoute({
 *   task: 'Analyze quarterly financials',
 *   priority: 'high',
 * });
 *
 * // Create a routing rule
 * const rule = await client.routing.createRule({
 *   name: 'Legal Escalation',
 *   conditions: [{ field: 'domain', operator: 'eq', value: 'legal' }],
 *   actions: [{ type: 'escalate_to', target: 'legal-team' }],
 * });
 * ```
 */
export class RoutingAPI {
  constructor(private client: RoutingClientInterface) {}

  // =========================================================================
  // Team Selection
  // =========================================================================

  /**
   * Get best team compositions for a task.
   */
  async getBestTeams(
    options?: BestTeamsOptions
  ): Promise<{ teams: TeamComposition[]; total: number }> {
    return this.client.request('GET', '/api/routing/best-teams', {
      params: options as unknown as Record<string, unknown>,
    });
  }

  /**
   * Get agent recommendations for a task.
   */
  async getRecommendations(
    request: RecommendationsRequest
  ): Promise<{ recommendations: AgentRecommendation[] }> {
    return this.client.request('POST', '/api/routing/recommendations', {
      json: request as unknown as Record<string, unknown>,
    });
  }

  /**
   * Auto-route a task to the best destination.
   */
  async autoRoute(request: AutoRouteRequest): Promise<AutoRouteResponse> {
    return this.client.request('POST', '/api/routing/auto-route', {
      json: request as unknown as Record<string, unknown>,
    });
  }

  /**
   * Detect the domain(s) for a task.
   */
  async detectDomain(
    task: string,
    options?: { top_n?: number }
  ): Promise<DomainDetection> {
    return this.client.request('POST', '/api/routing/detect-domain', {
      json: { task, ...options },
    });
  }

  /**
   * Get domain leaderboard.
   */
  async getDomainLeaderboard(
    options?: { domain?: string; limit?: number }
  ): Promise<{ leaderboard: DomainLeaderboardEntry[] }> {
    return this.client.request('POST', '/api/routing/domain-leaderboard', {
      params: options as unknown as Record<string, unknown>,
    });
  }

  // =========================================================================
  // Routing Rules
  // =========================================================================

  /**
   * List routing rules.
   */
  async listRules(
    options?: ListRulesOptions
  ): Promise<{ rules: RoutingRule[]; total: number }> {
    return this.client.request('GET', '/api/v1/routing-rules', {
      params: options as unknown as Record<string, unknown>,
    });
  }

  /**
   * Create a routing rule.
   */
  async createRule(request: CreateRuleRequest): Promise<RoutingRule> {
    return this.client.request('GET', '/api/v1/routing-rules', {
      json: request as unknown as Record<string, unknown>,
    });
  }

  /**
   * Get a routing rule by ID.
   */
  async getRule(ruleId: string): Promise<RoutingRule> {
    return this.client.request(
      'GET',
      `/api/v1/routing-rules/${encodeURIComponent(ruleId)}`
    );
  }

  /**
   * Update a routing rule.
   */
  async updateRule(ruleId: string, updates: UpdateRuleRequest): Promise<RoutingRule> {
    return this.client.request('GET', `/api/v1/routing-rules/${encodeURIComponent(ruleId)}`,
      {
        json: updates as unknown as Record<string, unknown>,
      }
    );
  }

  /**
   * Delete a routing rule.
   */
  async deleteRule(ruleId: string): Promise<{ success: boolean; message: string }> {
    return this.client.request('GET', `/api/v1/routing-rules/${encodeURIComponent(ruleId)}`
    );
  }

  /**
   * Toggle a routing rule on/off.
   */
  async toggleRule(
    ruleId: string,
    enabled: boolean
  ): Promise<{ rule_id: string; enabled: boolean }> {
    return this.client.request('GET', `/api/v1/routing-rules/${encodeURIComponent(ruleId)}/toggle`,
      {
        json: { enabled },
      }
    );
  }

  /**
   * Evaluate routing rules against a context.
   */
  async evaluateRules(
    request: EvaluateRulesRequest
  ): Promise<{ results: RuleEvaluationResult[]; matched_count: number }> {
    return this.client.request('GET', '/api/v1/routing-rules/evaluate', {
      json: request as unknown as Record<string, unknown>,
    });
  }

  /**
   * Get available rule templates.
   */
  async getRuleTemplates(): Promise<{ templates: RuleTemplate[] }> {
    return this.client.request('GET', '/api/v1/routing-rules/templates');
  }

  // =========================================================================
  // Message Bindings
  // =========================================================================

  /**
   * List all message bindings.
   */
  async listBindings(params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/bindings', { params });
  }

  /**
   * Get bindings for a specific provider.
   *
   * @param provider - Provider name (e.g., 'slack', 'telegram')
   */
  async getBindingsByProvider(provider: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/bindings/${encodeURIComponent(provider)}`);
  }

  /**
   * Create a message binding.
   */
  async createBinding(data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('POST', '/api/v1/bindings', { json: data });
  }

  /**
   * Resolve a message binding.
   */
  async resolveBinding(data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('POST', '/api/v1/bindings/resolve', { json: data });
  }

  /**
   * Get binding statistics.
   */
  async getBindingStats(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/bindings/stats');
  }

  /**
   * Delete a message binding.
   *
   * @param bindingId - Binding ID to delete
   */
  async deleteBinding(bindingId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/bindings/${encodeURIComponent(bindingId)}`);
  }

  /**
   * Delete a specific binding by provider, account, and peer pattern.
   *
   * This is the canonical 3-segment delete endpoint used for removing
   * specific message routing bindings.
   *
   * @param provider - Provider name (e.g. 'slack', 'telegram')
   * @param accountId - Account identifier
   * @param peerPattern - Peer pattern to unbind
   */
  async deleteProviderBinding(provider: string, accountId: string, peerPattern: string): Promise<Record<string, unknown>> {
    return this.client.request('DELETE', `/api/v1/bindings/${encodeURIComponent(provider)}/${encodeURIComponent(accountId)}/${encodeURIComponent(peerPattern)}`);
  }
}
