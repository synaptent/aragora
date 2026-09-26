/**
 * Control Plane API
 *
 * Handles enterprise control plane operations including agent registration,
 * task scheduling, health monitoring, deliberations, and policy violations.
 */

import { BaseAPI, HttpClient } from './base';

// =============================================================================
// Types
// =============================================================================

export type AgentStatus = 'active' | 'inactive' | 'unhealthy' | 'unregistered';
export type TaskStatus = 'pending' | 'claimed' | 'running' | 'completed' | 'failed' | 'cancelled';
export type TaskPriority = 'low' | 'normal' | 'high' | 'critical';
export type ViolationSeverity = 'low' | 'medium' | 'high' | 'critical';
export type ViolationStatus = 'open' | 'acknowledged' | 'resolved' | 'dismissed';

export interface Agent {
  id: string;
  name: string;
  type: string;
  status: AgentStatus;
  capabilities: string[];
  metadata?: Record<string, unknown>;
  last_heartbeat?: string;
  registered_at: string;
}

export interface AgentRegistration {
  name: string;
  type: string;
  capabilities?: string[];
  metadata?: Record<string, unknown>;
}

export interface AgentHealth {
  agent_id: string;
  status: AgentStatus;
  last_heartbeat?: string;
  latency_ms?: number;
  error?: string;
}

export interface Task {
  id: string;
  type: string;
  status: TaskStatus;
  priority: TaskPriority;
  payload: Record<string, unknown>;
  result?: Record<string, unknown>;
  error?: string;
  claimed_by?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
}

export interface TaskSubmission {
  type: string;
  payload: Record<string, unknown>;
  priority?: TaskPriority;
  timeout_seconds?: number;
  metadata?: Record<string, unknown>;
}

export interface TaskResult {
  task_id: string;
  status: TaskStatus;
  result?: Record<string, unknown>;
}

export interface Deliberation {
  id: string;
  topic: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  result?: DeliberationResult;
  created_at: string;
  started_at?: string;
  completed_at?: string;
}

export interface DeliberationRequest {
  topic: string;
  context?: Record<string, unknown>;
  agents?: string[];
  timeout_seconds?: number;
}

export interface DeliberationResult {
  decision: string;
  confidence: number;
  reasoning: string[];
  votes?: Record<string, string>;
  dissent?: string[];
}

export interface SystemHealth {
  status: 'healthy' | 'degraded' | 'unhealthy';
  agents: { total: number; active: number; unhealthy: number };
  tasks: { pending: number; running: number };
  last_check: string;
}

export interface ControlPlaneStats {
  agents: { total: number; active: number; by_type: Record<string, number> };
  tasks: { total: number; completed: number; failed: number; pending: number; running: number };
  uptime_seconds: number;
  last_updated: string;
}

export interface QueueStatus {
  pending: Task[];
  running: Task[];
  total_pending: number;
  total_running: number;
}

export interface DashboardMetrics {
  throughput: { tasks_per_minute: number; tasks_per_hour: number };
  latency: { avg_task_duration_ms: number; p95_task_duration_ms: number };
  health: SystemHealth;
  recent_failures: Task[];
}

export interface PolicyViolation {
  id: string;
  policy_id: string;
  policy_name: string;
  severity: ViolationSeverity;
  status: ViolationStatus;
  description: string;
  resource_id?: string;
  resource_type?: string;
  detected_at: string;
  resolved_at?: string;
  metadata?: Record<string, unknown>;
}

export interface ViolationStats {
  total: number;
  by_severity: Record<ViolationSeverity, number>;
  by_status: Record<ViolationStatus, number>;
  by_policy: Record<string, number>;
  trend: { last_24h: number; last_7d: number; last_30d: number };
}

export interface ViolationUpdateRequest {
  status?: ViolationStatus;
  resolution_notes?: string;
}

export interface ViolationListParams {
  severity?: ViolationSeverity;
  status?: ViolationStatus;
  policy_id?: string;
  limit?: number;
  offset?: number;
}

// =============================================================================
// Control Plane API Class
// =============================================================================

export class ControlPlaneAPI extends BaseAPI {
  constructor(http: HttpClient) {
    super(http);
  }

  // ===========================================================================
  // Agent Management
  // ===========================================================================

  /**
   * List all registered agents
   */
  async listAgents(): Promise<Agent[]> {
    return this.http.get('/api/v1/control-plane/agents');
  }

  /**
   * Register a new agent
   */
  async registerAgent(data: AgentRegistration): Promise<Agent> {
    return this.http.post('/api/v1/control-plane/agents', data);
  }

  /**
   * Get agent information
   */
  async getAgent(agentId: string): Promise<Agent> {
    return this.http.get(`/api/v1/control-plane/agents/${agentId}`);
  }

  /**
   * Unregister (delete) an agent
   */
  async unregisterAgent(agentId: string): Promise<void> {
    return this.http.delete(`/api/v1/control-plane/agents/${agentId}`);
  }

  /**
   * Send a heartbeat for an agent
   */
  async heartbeat(agentId: string): Promise<{ acknowledged: boolean }> {
    return this.http.post(`/api/v1/control-plane/agents/${agentId}/heartbeat`, {});
  }

  /**
   * Get agent health status
   */
  async getAgentHealth(agentId: string): Promise<AgentHealth> {
    return this.http.get(`/api/v1/control-plane/health/${agentId}`);
  }

  // ===========================================================================
  // Task Management
  // ===========================================================================

  /**
   * Submit a new task
   */
  async submitTask(task: TaskSubmission): Promise<Task> {
    return this.http.post('/api/v1/control-plane/tasks', task);
  }

  /**
   * Get task status and details
   */
  async getTask(taskId: string): Promise<Task> {
    return this.http.get(`/api/v1/control-plane/tasks/${taskId}`);
  }

  /**
   * Claim the next available task
   */
  async claimTask(agentId?: string): Promise<Task | null> {
    return this.http.post('/api/v1/control-plane/tasks/claim', { agent_id: agentId });
  }

  /**
   * Mark a task as completed
   */
  async completeTask(taskId: string, result: Record<string, unknown>): Promise<TaskResult> {
    return this.http.post(`/api/v1/control-plane/tasks/${taskId}/complete`, { result });
  }

  /**
   * Mark a task as failed
   */
  async failTask(taskId: string, error: string): Promise<TaskResult> {
    return this.http.post(`/api/v1/control-plane/tasks/${taskId}/fail`, { error });
  }

  /**
   * Cancel a task
   */
  async cancelTask(taskId: string): Promise<TaskResult> {
    return this.http.post(`/api/v1/control-plane/tasks/${taskId}/cancel`, {});
  }

  // ===========================================================================
  // Deliberations (AI Debate)
  // ===========================================================================

  /**
   * Start or queue a deliberation session
   */
  async startDeliberation(request: DeliberationRequest): Promise<Deliberation> {
    return this.http.post('/api/v1/control-plane/deliberations', request);
  }

  /**
   * Get deliberation result
   */
  async getDeliberation(deliberationId: string): Promise<Deliberation> {
    return this.http.get(`/api/v1/control-plane/deliberations/${deliberationId}`);
  }

  /**
   * Get deliberation status (lightweight)
   */
  async getDeliberationStatus(
    deliberationId: string,
  ): Promise<{ status: string; progress?: number }> {
    return this.http.get(`/api/v1/control-plane/deliberations/${deliberationId}/status`);
  }

  // ===========================================================================
  // Health & Monitoring
  // ===========================================================================

  /**
   * Get system health status
   */
  async getHealth(): Promise<SystemHealth> {
    return this.http.get('/api/v1/control-plane/health');
  }

  /**
   * Get control plane statistics
   */
  async getStats(): Promise<ControlPlaneStats> {
    return this.http.get('/api/v1/control-plane/stats');
  }

  /**
   * Get job queue status
   */
  async getQueue(): Promise<QueueStatus> {
    return this.http.get('/api/v1/control-plane/queue');
  }

  /**
   * Get dashboard metrics
   */
  async getMetrics(): Promise<DashboardMetrics> {
    return this.http.get('/api/v1/control-plane/metrics');
  }

  // ===========================================================================
  // Policy Violations
  // ===========================================================================

  /**
   * List policy violations
   */
  async listViolations(params?: ViolationListParams): Promise<PolicyViolation[]> {
    const searchParams = new URLSearchParams();
    if (params?.severity) searchParams.set('severity', params.severity);
    if (params?.status) searchParams.set('status', params.status);
    if (params?.policy_id) searchParams.set('policy_id', params.policy_id);
    if (params?.limit) searchParams.set('limit', params.limit.toString());
    if (params?.offset) searchParams.set('offset', params.offset.toString());

    const query = searchParams.toString();
    return this.http.get(`/api/v1/control-plane/policies/violations${query ? `?${query}` : ''}`);
  }

  /**
   * Get policy violation statistics
   */
  async getViolationStats(): Promise<ViolationStats> {
    return this.http.get('/api/v1/control-plane/policies/violations/stats');
  }

  /**
   * Get violation details
   */
  async getViolation(violationId: string): Promise<PolicyViolation> {
    return this.http.get(`/api/v1/control-plane/policies/violations/${violationId}`);
  }

  /**
   * Update violation status (acknowledge, resolve, dismiss)
   */
  async updateViolation(
    violationId: string,
    update: ViolationUpdateRequest,
  ): Promise<PolicyViolation> {
    return this.http.patch(`/api/v1/control-plane/policies/violations/${violationId}`, update);
  }
}
