/**
 * Decisions Namespace API
 *
 * Provides a namespaced interface for unified decision-making.
 * Routes decisions through debate, workflow, or gauntlet based on
 * the content and configuration.
 */

/**
 * Decision type
 */
export type DecisionType = 'debate' | 'workflow' | 'gauntlet' | 'quick' | 'auto';

/**
 * Decision priority
 */
export type DecisionPriority = 'high' | 'normal' | 'low';

/**
 * Decision status
 */
export type DecisionStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'timeout';

/**
 * Response channel configuration
 */
export interface ResponseChannel {
  platform: 'http_api' | 'slack' | 'teams' | 'discord' | 'email' | 'webhook';
  config?: Record<string, unknown>;
}

/**
 * Decision context
 */
export interface DecisionContext {
  user_id?: string;
  workspace_id?: string;
  org_id?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Decision configuration
 */
export interface DecisionConfig {
  agents?: string[];
  rounds?: number;
  consensus?: 'majority' | 'unanimous' | 'supermajority';
  timeout_seconds?: number;
  required_capabilities?: string[];
}

/**
 * Decision request
 */
export interface DecisionRequest {
  content: string;
  decision_type?: DecisionType;
  config?: DecisionConfig;
  context?: DecisionContext;
  priority?: DecisionPriority;
  response_channels?: ResponseChannel[];
  async?: boolean;
}

/**
 * Decision result
 */
export interface DecisionResult {
  request_id: string;
  status: DecisionStatus;
  decision_type: DecisionType;
  answer?: string;
  confidence?: number;
  consensus_reached?: boolean;
  reasoning?: string;
  evidence_used?: string[];
  duration_seconds?: number;
  error?: string;
  completed_at?: string;
}

/**
 * Decision status response
 */
export interface DecisionStatusResponse {
  request_id: string;
  status: DecisionStatus;
  completed_at?: string;
}

/**
 * Decision summary
 */
export interface DecisionSummary {
  request_id: string;
  status: DecisionStatus;
  decision_type?: DecisionType;
  completed_at?: string;
}

/**
 * Decision list response
 */
export interface DecisionListResponse {
  decisions: DecisionSummary[];
  total: number;
}

/**
 * Interface for the internal client used by DecisionsAPI.
 */
interface DecisionsClientInterface {
  get<T>(path: string): Promise<T>;
  post<T>(path: string, body?: unknown): Promise<T>;
  request<T>(method: string, path: string, options?: { params?: Record<string, unknown>; body?: unknown }): Promise<T>;
}

/**
 * Decisions API namespace.
 *
 * Provides methods for unified decision-making:
 * - Submit decisions for debate, workflow, or gauntlet routing
 * - Poll for decision status and results
 * - List recent decisions
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai', apiKey: 'your-key' });
 *
 * // Submit a decision request
 * const result = await client.decisions.create({
 *   content: 'Should we migrate to TypeScript?',
 *   decision_type: 'debate',
 *   config: {
 *     agents: ['anthropic-api', 'openai-api', 'gemini-api'],
 *     rounds: 3,
 *     consensus: 'majority',
 *   },
 *   context: {
 *     workspace_id: 'ws-123',
 *   },
 * });
 *
 * console.log(`Decision: ${result.answer} (confidence: ${result.confidence})`);
 *
 * // Poll for async decision status
 * const status = await client.decisions.getStatus(result.request_id);
 *
 * // List recent decisions
 * const { decisions } = await client.decisions.list({ limit: 20 });
 * ```
 */
export class DecisionsAPI {
  constructor(private client: DecisionsClientInterface) {}

  /**
   * Create a new decision request.
   * Routes to debate, workflow, or gauntlet based on content and config.
   * @param body - Decision request configuration
   */
  async create(body: DecisionRequest): Promise<DecisionResult> {
    return this.client.post('/api/v1/decisions', body);
  }

  /**
   * Get a decision result by request ID.
   * @param requestId - The decision request ID
   */
  async get(requestId: string): Promise<DecisionResult> {
    return this.client.get(`/api/v1/decisions/${requestId}`);
  }

  /**
   * Get decision status for polling.
   * @param requestId - The decision request ID
   */
  async getStatus(requestId: string): Promise<DecisionStatusResponse> {
    return this.client.get(`/api/v1/decisions/${requestId}/status`);
  }

  /**
   * Get explainability details for a decision request.
   * @param requestId - The decision request ID
   */
  async getExplain(requestId: string): Promise<Record<string, unknown>> {
    return this.client.get(`/api/v1/decisions/${requestId}/explain`);
  }

  /**
   * List recent decisions.
   * @param options - Filter options
   */
  async list(options?: { limit?: number }): Promise<DecisionListResponse> {
    return this.client.request('GET', '/api/v1/decisions', { params: options });
  }

  /**
   * Wait for a decision to complete (polling helper).
   * @param requestId - The decision request ID
   * @param options - Polling configuration
   */
  async waitForCompletion(
    requestId: string,
    options?: { intervalMs?: number; timeoutMs?: number }
  ): Promise<DecisionResult> {
    const { intervalMs = 1000, timeoutMs = 300000 } = options || {};
    const startTime = Date.now();

    while (Date.now() - startTime < timeoutMs) {
      const status = await this.getStatus(requestId);

      if (status.status === 'completed' || status.status === 'failed' || status.status === 'timeout') {
        return this.get(requestId);
      }

      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }

    throw new Error(`Decision ${requestId} did not complete within ${timeoutMs}ms`);
  }

  // ---------------------------------------------------------------------------
  // DecisionPlan methods (gold path: debate → plan → execute → verify)
  // ---------------------------------------------------------------------------

  /**
   * Create a DecisionPlan from a completed debate.
   * @param debateId - ID of the completed debate
   * @param options - Plan creation options
   */
  async createPlan(
    debateId: string,
    options?: {
      budget_limit_usd?: number;
      approval_mode?: ApprovalMode;
      max_auto_risk?: RiskLevel;
      metadata?: Record<string, unknown>;
    }
  ): Promise<DecisionPlanResponse> {
    const body = {
      debate_id: debateId,
      ...options,
    };
    return this.client.post('/api/v1/decisions/plans', body);
  }

  /**
   * Get a DecisionPlan by ID.
   * @param planId - Plan identifier
   */
  async getPlan(planId: string): Promise<DecisionPlanResponse> {
    return this.client.get(`/api/v1/decisions/plans/${planId}`);
  }

  /**
   * List DecisionPlans with optional filtering.
   * @param options - Filter options
   */
  async listPlans(options?: {
    status?: PlanStatus;
    limit?: number;
  }): Promise<DecisionPlanListResponse> {
    return this.client.request('GET', '/api/v1/decisions/plans', { params: options });
  }

  /**
   * Approve a DecisionPlan for execution.
   * @param planId - Plan identifier
   * @param options - Approval options
   */
  async approvePlan(
    planId: string,
    options?: { reason?: string; conditions?: string[] }
  ): Promise<DecisionPlanApprovalResponse> {
    return this.client.request('POST', `/api/v1/decisions/plans/${planId}/approve`, {
      body: options,
    });
  }

  /**
   * Reject a DecisionPlan.
   * @param planId - Plan identifier
   * @param reason - Reason for rejection
   */
  async rejectPlan(planId: string, reason?: string): Promise<DecisionPlanApprovalResponse> {
    return this.client.request('POST', `/api/v1/decisions/plans/${planId}/reject`, {
      body: { reason },
    });
  }

  /**
   * Execute an approved DecisionPlan.
   * @param planId - Plan identifier
   */
  async executePlan(planId: string): Promise<DecisionPlanExecutionResponse> {
    return this.client.request('POST', `/api/v1/decisions/plans/${planId}/execute`);
  }

  /**
   * Get the execution outcome for a completed plan.
   * @param planId - Plan identifier
   */
  async getPlanOutcome(planId: string): Promise<PlanOutcomeResponse> {
    return this.client.request('GET', `/api/v1/decisions/plans/${planId}/outcome`);
  }

  /** List all outcomes for a decision. */
  async listOutcomes(decisionId: string): Promise<Record<string, unknown>> {
    return this.client.get(`/api/v1/decisions/${decisionId}/outcomes`);
  }

  /**
   * Cancel a pending or processing decision.
   *
   * Only decisions in PENDING or PROCESSING status can be cancelled.
   *
   * @param decisionId - The decision request ID to cancel
   * @param reason - Optional reason for cancellation
   *
   * @example
   * ```typescript
   * const result = await client.decisions.cancel('req-123', 'No longer needed');
   * console.log(`Cancelled at: ${result.cancelled_at}`);
   * ```
   */
  async cancel(decisionId: string, reason?: string): Promise<{ request_id: string; status: DecisionStatus; cancelled_at: string }> {
    return this.client.request('POST', `/api/v1/decisions/${decisionId}/cancel`, { params: reason ? { reason } : {} });
  }

  /**
   * Retry a failed or cancelled decision.
   *
   * Creates a new decision request with the same parameters as the original.
   *
   * @param decisionId - The decision request ID to retry
   *
   * @example
   * ```typescript
   * const retried = await client.decisions.retry('req-123');
   * console.log(`New request ID: ${retried.request_id}`);
   * ```
   */
  async retry(decisionId: string): Promise<DecisionResult> {
    return this.client.request('POST', `/api/v1/decisions/${decisionId}/retry`);
  }

  // -------------------------------------------------------------------------
  // Decision workspace
  // -------------------------------------------------------------------------

  /** Agents a workspace decision can use, the intake limits and accepted file types. */
  async getWorkspaceAgentOptions(): Promise<WorkspaceAgentOptions> {
    return this.client.get('/api/v1/workspace/agent-options');
  }

  /** List the caller's organization's workspace decisions, newest first. */
  async listWorkspaceDecisions(options?: {
    limit?: number;
    offset?: number;
  }): Promise<WorkspaceDecisionList> {
    return this.client.request('GET', '/api/v1/workspace/decisions', { params: options });
  }

  /** Get one workspace decision. */
  async getWorkspaceDecision(decisionId: string): Promise<WorkspaceDecision> {
    return this.client.get(`/api/v1/workspace/decisions/${decisionId}`);
  }

  /** List a workspace decision's sources with their passage summaries. */
  async listWorkspaceDecisionSources(decisionId: string): Promise<WorkspaceDecisionSources> {
    return this.client.get(`/api/v1/workspace/decisions/${decisionId}/sources`);
  }

  /** Get the exact text, label and SHA-256 of one passage. */
  async getWorkspaceDecisionPassage(
    decisionId: string,
    passageId: string
  ): Promise<WorkspacePassage> {
    return this.client.get(`/api/v1/workspace/decisions/${decisionId}/passages/${passageId}`);
  }

  /**
   * Start a workspace decision from a question and pasted text.
   *
   * File uploads use multipart/form-data, which this client does not send.
   */
  async createWorkspaceDecision(body: WorkspaceDecisionRequest): Promise<WorkspaceCreatedDecision> {
    return this.client.request('POST', '/api/v1/workspace/decisions', { body });
  }
}

// ---------------------------------------------------------------------------
// Decision workspace types
// ---------------------------------------------------------------------------

export type WorkspaceDecisionStatus = 'debating' | 'ready' | 'failed';

export interface WorkspaceAgentOption {
  spec: string;
  provider: string;
  model: string | null;
}

export interface WorkspaceAgentOptions {
  configured: boolean;
  agents: WorkspaceAgentOption[];
  message: string | null;
  limits: { max_documents: number; max_file_bytes: number; max_pasted_chars: number };
  accepted_extensions: string[];
  rounds: { min: number; max: number; default: number };
}

export interface WorkspaceDecisionSummary {
  id: string;
  question: string;
  status: WorkspaceDecisionStatus;
  source_count: number;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceDecisionList {
  decisions: WorkspaceDecisionSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface WorkspaceDecision {
  id: string;
  question: string;
  status: WorkspaceDecisionStatus;
  agents: string[];
  rounds: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  current_revision_id: string | null;
  budget_usd: number | null;
  cost_actual_usd: number;
  cost_estimated_usd: number;
  source_count: number;
  passage_count: number;
}

export interface WorkspacePassageSummary {
  passage_id: string;
  label: string;
  seq: number;
  heading: string | null;
  char_count: number;
  sha256: string;
  in_context: boolean;
}

export interface WorkspaceSource {
  source_id: string;
  label: string;
  kind: 'upload' | 'pasted';
  filename: string | null;
  document_id: string | null;
  content_sha256: string;
  char_count: number;
  passage_count: number;
  created_at: string;
  passages: WorkspacePassageSummary[];
}

export interface WorkspaceDecisionSources {
  decision_id: string;
  sources: WorkspaceSource[];
}

export interface WorkspacePassage {
  passage_id: string;
  decision_id: string;
  source_id: string;
  source_label: string;
  label: string;
  seq: number;
  heading: string | null;
  start_char: number;
  end_char: number;
  text: string;
  sha256: string;
  in_context: boolean;
  created_at: string;
}

export interface WorkspaceDecisionRequest {
  question: string;
  agents: string[];
  pasted_text?: string;
  rounds?: number;
}

export interface WorkspaceCreatedDecision extends WorkspaceDecision, WorkspaceDecisionSources {}

// ---------------------------------------------------------------------------
// DecisionPlan types
// ---------------------------------------------------------------------------

/**
 * Plan status values
 */
export type PlanStatus =
  | 'created'
  | 'awaiting_approval'
  | 'approved'
  | 'rejected'
  | 'executing'
  | 'verifying'
  | 'completed'
  | 'failed'
  | 'rolled_back';

/**
 * Approval mode for plans
 */
export type ApprovalMode = 'always' | 'risk_based' | 'confidence_based' | 'never';

/**
 * Risk level
 */
export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';

/**
 * Plan approval record
 */
export interface PlanApprovalRecord {
  approved: boolean;
  approver_id: string;
  timestamp: string;
  reason?: string;
  conditions?: string[];
}

/**
 * Budget allocation
 */
export interface BudgetAllocation {
  limit_usd: number | null;
  spent_usd: number;
  remaining_usd: number | null;
}

/**
 * DecisionPlan details
 */
export interface DecisionPlan {
  id: string;
  debate_id: string;
  task: string;
  status: PlanStatus;
  risk_level?: RiskLevel;
  requires_human_approval: boolean;
  budget?: BudgetAllocation;
  approval_record?: PlanApprovalRecord;
  created_at?: string;
  updated_at?: string;
}

/**
 * Response for plan operations
 */
export interface DecisionPlanResponse {
  success: boolean;
  plan: DecisionPlan;
  outcome?: PlanOutcome;
  error?: string;
}

/**
 * Response for plan list
 */
export interface DecisionPlanListResponse {
  success: boolean;
  plans: DecisionPlan[];
  count: number;
}

/**
 * Response for plan approval/rejection
 */
export interface DecisionPlanApprovalResponse {
  success: boolean;
  plan: {
    id: string;
    status: PlanStatus;
    approval_record?: PlanApprovalRecord;
  };
}

/**
 * Response for plan execution
 */
export interface DecisionPlanExecutionResponse {
  success: boolean;
  plan: DecisionPlan;
  outcome: PlanOutcome;
}

/**
 * Plan execution outcome
 */
export interface PlanOutcome {
  plan_id: string;
  debate_id: string;
  task: string;
  success: boolean;
  tasks_completed: number;
  tasks_total: number;
  verification_passed?: number;
  verification_total?: number;
  total_cost_usd: number;
  error?: string;
  lessons?: string[];
}

/**
 * Response for plan outcome
 */
export interface PlanOutcomeResponse {
  success: boolean;
  outcome: PlanOutcome;
}
