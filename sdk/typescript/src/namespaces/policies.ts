/**
 * Policies Namespace API
 *
 * Provides access to governance policies, compliance rules, and violation tracking.
 */

/**
 * Policy types
 */
export type PolicyType =
  | 'content_filter'
  | 'rate_limit'
  | 'access_control'
  | 'data_retention'
  | 'compliance'
  | 'budget'
  | 'custom';

/**
 * Policy severity levels
 */
export type PolicySeverity = 'low' | 'medium' | 'high' | 'critical';

/**
 * Policy enforcement actions
 */
export type PolicyAction = 'warn' | 'block' | 'audit' | 'notify' | 'escalate';

/**
 * Policy definition
 */
export interface Policy {
  id: string;
  name: string;
  description: string;
  type: PolicyType;
  severity: PolicySeverity;
  enabled: boolean;
  rules: PolicyRule[];
  actions: PolicyAction[];
  created_at: string;
  updated_at: string;
  created_by?: string;
  applies_to?: string[];
  exemptions?: string[];
}

/**
 * Policy rule definition
 */
export interface PolicyRule {
  id: string;
  field: string;
  operator: 'eq' | 'ne' | 'gt' | 'lt' | 'gte' | 'lte' | 'contains' | 'regex' | 'in' | 'not_in';
  value: unknown;
  description?: string;
}

/**
 * Policy violation record
 */
export interface PolicyViolation {
  id: string;
  policy_id: string;
  policy_name: string;
  severity: PolicySeverity;
  rule_id: string;
  rule_field: string;
  actual_value: unknown;
  expected: string;
  action_taken: PolicyAction;
  context: Record<string, unknown>;
  occurred_at: string;
  resolved_at?: string;
  resolved_by?: string;
  resolution_notes?: string;
}

/**
 * Policy compliance summary
 */
export interface ComplianceSummary {
  total_policies: number;
  enabled_policies: number;
  violations_today: number;
  violations_this_week: number;
  violation_trend: 'increasing' | 'decreasing' | 'stable';
  compliance_score: number;
  by_severity: Record<PolicySeverity, number>;
  by_type: Record<PolicyType, number>;
  last_updated: string;
}

/**
 * Create policy request
 */
export interface CreatePolicyRequest {
  name: string;
  description: string;
  type: PolicyType;
  severity: PolicySeverity;
  rules: Array<Omit<PolicyRule, 'id'>>;
  actions: PolicyAction[];
  enabled?: boolean;
  applies_to?: string[];
  exemptions?: string[];
}

/**
 * Update policy request
 */
export interface UpdatePolicyRequest {
  name?: string;
  description?: string;
  severity?: PolicySeverity;
  rules?: Array<Omit<PolicyRule, 'id'>>;
  actions?: PolicyAction[];
  applies_to?: string[];
  exemptions?: string[];
}

/**
 * Interface for the internal client used by PoliciesAPI.
 */
interface PoliciesClientInterface {
  request<T>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }
  ): Promise<T>;
}

/**
 * Policies API namespace.
 *
 * Provides methods for managing governance policies:
 * - Create, update, and delete policies
 * - View and resolve policy violations
 * - Track compliance metrics
 * - Manage policy rules and actions
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai', apiKey: 'your-key' });
 *
 * // List all policies
 * const { policies } = await client.policies.list();
 *
 * // Create a new policy
 * const policy = await client.policies.create({
 *   name: 'Max Budget Policy',
 *   type: 'budget',
 *   severity: 'high',
 *   rules: [{ field: 'monthly_spend', operator: 'lte', value: 1000 }],
 *   actions: ['warn', 'notify']
 * });
 *
 * // Get violations
 * const { violations } = await client.policies.getViolations(policy.id);
 * ```
 */
export class PoliciesAPI {
  constructor(private client: PoliciesClientInterface) {}

  /**
   * List all policies.
   */
  async list(options?: {
    type?: PolicyType;
    severity?: PolicySeverity;
    enabled?: boolean;
    limit?: number;
    offset?: number;
  }): Promise<{ policies: Policy[]; total: number }> {
    return this.client.request('GET', '/api/policies', { params: options });
  }

  /**
   * Get a specific policy by ID.
   */
  async get(policyId: string): Promise<Policy> {
    return this.client.request('GET', `/api/policies/${policyId}`);
  }

  /**
   * Create a new policy.
   */
  async create(policy: CreatePolicyRequest): Promise<Policy> {
    return this.client.request('POST', '/api/policies', {
      json: policy as unknown as Record<string, unknown>,
    });
  }

  /**
   * Update an existing policy.
   */
  async update(policyId: string, updates: UpdatePolicyRequest): Promise<Policy> {
    return this.client.request('PATCH', `/api/policies/${policyId}`, {
      json: updates as unknown as Record<string, unknown>,
    });
  }

  /**
   * Delete a policy.
   */
  async delete(policyId: string): Promise<{ success: boolean }> {
    return this.client.request('DELETE', `/api/policies/${policyId}`);
  }

  /**
   * Toggle a policy's enabled status.
   */
  async toggle(policyId: string): Promise<{ enabled: boolean }> {
    return this.client.request('POST', `/api/policies/${policyId}/toggle`);
  }

  /**
   * Get violations for a specific policy.
   */
  async getViolations(
    policyId: string,
    options?: {
      resolved?: boolean;
      severity?: PolicySeverity;
      since?: string;
      limit?: number;
      offset?: number;
    }
  ): Promise<{ violations: PolicyViolation[]; total: number }> {
    return this.client.request('GET', `/api/policies/${policyId}/violations`, { params: options });
  }

  /**
   * Get all violations across policies.
   */
  async getAllViolations(options?: {
    policy_type?: PolicyType;
    severity?: PolicySeverity;
    resolved?: boolean;
    since?: string;
    limit?: number;
    offset?: number;
  }): Promise<{ violations: PolicyViolation[]; total: number }> {
    return this.client.request('GET', '/api/policies/violations', { params: options });
  }

  /**
   * Resolve a policy violation.
   */
  async resolveViolation(
    violationId: string,
    resolution: { notes?: string }
  ): Promise<PolicyViolation> {
    return this.client.request('POST', `/api/policies/violations/${violationId}/resolve`, {
      json: resolution,
    });
  }

  /**
   * Get compliance summary.
   */
  async getComplianceSummary(): Promise<ComplianceSummary> {
    return this.client.request('GET', '/api/compliance/summary');
  }

  /**
   * Validate a policy configuration without saving.
   */
  async validate(policy: CreatePolicyRequest): Promise<{ valid: boolean; errors?: string[] }> {
    return this.client.request('POST', '/api/policies/validate', {
      json: policy as unknown as Record<string, unknown>,
    });
  }
}
