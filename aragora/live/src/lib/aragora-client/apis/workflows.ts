/**
 * Workflows API
 *
 * Handles workflow creation, execution, and management.
 */

import { BaseAPI, HttpClient } from './base';

// =============================================================================
// Types
// =============================================================================

export interface WorkflowNode {
  id: string;
  type: string;
  config: Record<string, unknown>;
  dependencies?: string[];
}

export interface Workflow {
  id: string;
  name: string;
  description?: string;
  nodes: WorkflowNode[];
  status: 'draft' | 'active' | 'paused' | 'completed' | 'failed';
  created_at: string;
  updated_at: string;
  created_by: string;
  execution_count?: number;
  last_execution_at?: string;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  nodes: WorkflowNode[];
  parameters: Array<{
    name: string;
    type: string;
    required: boolean;
    default?: unknown;
    description?: string;
  }>;
}

export interface WorkflowExecution {
  id: string;
  workflow_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  started_at: string;
  completed_at?: string;
  result?: unknown;
  error?: string;
  progress: number;
  current_node?: string;
}

export interface WorkflowCreateRequest {
  name: string;
  description?: string;
  nodes: WorkflowNode[];
  template_id?: string;
  parameters?: Record<string, unknown>;
}

// =============================================================================
// Workflows API Class
// =============================================================================

export class WorkflowsAPI extends BaseAPI {
  constructor(http: HttpClient) {
    super(http);
  }

  /**
   * List all workflows
   */
  async list(status?: string): Promise<{ workflows: Workflow[] }> {
    const path = status ? `/api/workflows?status=${status}` : '/api/workflows';
    return this.http.get(path);
  }

  /**
   * Get a specific workflow
   */
  async get(workflowId: string): Promise<{ workflow: Workflow }> {
    return this.http.get(`/api/workflows/${workflowId}`);
  }

  /**
   * Create a new workflow
   */
  async create(request: WorkflowCreateRequest): Promise<{ workflow: Workflow }> {
    return this.http.post('/api/workflows', request);
  }

  /**
   * Update a workflow
   */
  async update(
    workflowId: string,
    updates: Partial<WorkflowCreateRequest>,
  ): Promise<{ workflow: Workflow }> {
    return this.http.patch(`/api/workflows/${workflowId}`, updates);
  }

  /**
   * Delete a workflow
   */
  async delete(workflowId: string): Promise<{ message: string }> {
    return this.http.delete(`/api/workflows/${workflowId}`);
  }

  /**
   * Execute a workflow
   */
  async execute(
    workflowId: string,
    parameters?: Record<string, unknown>,
  ): Promise<{ execution: WorkflowExecution }> {
    return this.http.post(`/api/workflows/${workflowId}/execute`, { parameters });
  }

  /**
   * Get workflow execution status
   */
  async executionStatus(executionId: string): Promise<{ execution: WorkflowExecution }> {
    return this.http.get(`/api/workflows/executions/${executionId}`);
  }

  /**
   * List workflow executions
   */
  async executions(workflowId: string, limit = 10): Promise<{ executions: WorkflowExecution[] }> {
    return this.http.get(`/api/workflows/${workflowId}/executions?limit=${limit}`);
  }

  /**
   * Cancel a running execution
   */
  async cancelExecution(executionId: string): Promise<{ message: string }> {
    return this.http.post(`/api/workflows/executions/${executionId}/cancel`, {});
  }

  /**
   * List available workflow templates
   */
  async templates(category?: string): Promise<{ templates: WorkflowTemplate[] }> {
    const path = category
      ? `/api/workflows/templates?category=${category}`
      : '/api/workflows/templates';
    return this.http.get(path);
  }

  /**
   * Get a specific template
   */
  async template(templateId: string): Promise<{ template: WorkflowTemplate }> {
    return this.http.get(`/api/workflows/templates/${templateId}`);
  }

  /**
   * Create workflow from template
   */
  async fromTemplate(
    templateId: string,
    parameters: Record<string, unknown>,
  ): Promise<{ workflow: Workflow }> {
    return this.http.post(`/api/workflows/templates/${templateId}/instantiate`, { parameters });
  }
}
