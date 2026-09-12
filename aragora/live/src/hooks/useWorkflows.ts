'use client';

/**
 * Workflow Management hook for CRUD operations on workflows.
 *
 * Provides:
 * - List, create, update, delete workflows
 * - Execute and simulate workflows
 * - Version history and restore
 * - Approval management
 * - Template listing
 */

import { useState, useCallback, useEffect } from 'react';
import { useApi } from './useApi';
import { useBackend } from '@/components/BackendSelector';
import { logger } from '@/utils/logger';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface WorkflowStep {
  id: string;
  name: string;
  step_type: string;
  optional?: boolean;
  timeout_seconds?: number;
  next_steps?: string[];
  config?: Record<string, unknown>;
}

export interface Workflow {
  id: string;
  name: string;
  description?: string;
  category?: string;
  tags?: string[];
  steps: WorkflowStep[];
  entry_step?: string;
  created_by?: string;
  created_at?: string;
  updated_at?: string;
  version?: number;
  tenant_id?: string;
  metadata?: Record<string, unknown>;
}

export interface WorkflowVersion {
  version: number | string;
  created_at: string;
  created_by?: string;
  changes?: string;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description?: string;
  category?: string;
  tags?: string[];
  steps: WorkflowStep[];
}

export interface SimulationResult {
  workflow_id: string;
  is_valid: boolean;
  validation_errors: string[];
  execution_plan: Array<{
    step_id: string;
    step_name: string;
    step_type: string;
    optional: boolean;
    timeout: number | null;
  }>;
  estimated_steps: number;
}

export interface ApprovalRequest {
  id: string;
  workflow_id?: string;
  execution_id?: string;
  step_name?: string;
  status: string;
  requested_at?: string;
}

interface WorkflowListResponse {
  workflows?: Workflow[];
  items?: Workflow[];
  count?: number;
  total?: number;
}

interface VersionsResponse {
  versions: WorkflowVersion[];
  workflow_id: string;
}

interface TemplatesResponse {
  templates: WorkflowTemplate[];
  count: number;
}

interface ApprovalsResponse {
  approvals: ApprovalRequest[];
  count: number;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useWorkflows() {
  const { config: backendConfig } = useBackend();
  const api = useApi(backendConfig?.api);

  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // -------------------------------------------------------------------------
  // List workflows
  // -------------------------------------------------------------------------
  const fetchWorkflows = useCallback(
    async (params?: { limit?: number; offset?: number; category?: string; search?: string }) => {
      setLoading(true);
      setError(null);
      try {
        const query = new URLSearchParams();
        if (params?.limit) query.set('limit', String(params.limit));
        if (params?.offset) query.set('offset', String(params.offset));
        if (params?.category) query.set('category', params.category);
        if (params?.search) query.set('search', params.search);

        const qs = query.toString();
        const result = (await api.get(
          `/api/v1/workflows${qs ? `?${qs}` : ''}`,
        )) as WorkflowListResponse;
        const items = result?.workflows ?? result?.items ?? [];
        setWorkflows(items);
        return items;
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Failed to fetch workflows';
        setError(msg);
        logger.error('Failed to fetch workflows:', err);
        return [];
      } finally {
        setLoading(false);
      }
    },
    [api],
  );

  // -------------------------------------------------------------------------
  // Get single workflow
  // -------------------------------------------------------------------------
  const getWorkflow = useCallback(
    async (workflowId: string): Promise<Workflow | null> => {
      try {
        return (await api.get(`/api/v1/workflows/${encodeURIComponent(workflowId)}`)) as Workflow;
      } catch (err) {
        logger.error(`Failed to get workflow ${workflowId}:`, err);
        return null;
      }
    },
    [api],
  );

  // -------------------------------------------------------------------------
  // Create workflow
  // -------------------------------------------------------------------------
  const createWorkflow = useCallback(
    async (data: {
      name: string;
      steps: WorkflowStep[];
      description?: string;
      category?: string;
      tags?: string[];
    }): Promise<Workflow | null> => {
      try {
        const result = (await api.post('/api/v1/workflows', data)) as Workflow;
        // Refresh list
        await fetchWorkflows();
        return result;
      } catch (err) {
        logger.error('Failed to create workflow:', err);
        return null;
      }
    },
    [api, fetchWorkflows],
  );

  // -------------------------------------------------------------------------
  // Update workflow
  // -------------------------------------------------------------------------
  const updateWorkflow = useCallback(
    async (workflowId: string, updates: Partial<Workflow>): Promise<Workflow | null> => {
      try {
        const result = (await api.put(
          `/api/v1/workflows/${encodeURIComponent(workflowId)}`,
          updates,
        )) as Workflow;
        await fetchWorkflows();
        return result;
      } catch (err) {
        logger.error(`Failed to update workflow ${workflowId}:`, err);
        return null;
      }
    },
    [api, fetchWorkflows],
  );

  // -------------------------------------------------------------------------
  // Delete workflow
  // -------------------------------------------------------------------------
  const deleteWorkflow = useCallback(
    async (workflowId: string): Promise<boolean> => {
      try {
        await api.delete(`/api/v1/workflows/${encodeURIComponent(workflowId)}`);
        setWorkflows((prev) => prev.filter((w) => w.id !== workflowId));
        return true;
      } catch (err) {
        logger.error(`Failed to delete workflow ${workflowId}:`, err);
        return false;
      }
    },
    [api],
  );

  // -------------------------------------------------------------------------
  // Execute workflow
  // -------------------------------------------------------------------------
  const executeWorkflow = useCallback(
    async (
      workflowId: string,
      inputs?: Record<string, unknown>,
    ): Promise<Record<string, unknown> | null> => {
      try {
        return (await api.post(
          `/api/v1/workflows/${encodeURIComponent(workflowId)}/execute`,
          inputs ? { inputs } : {},
        )) as Record<string, unknown>;
      } catch (err) {
        logger.error(`Failed to execute workflow ${workflowId}:`, err);
        return null;
      }
    },
    [api],
  );

  // -------------------------------------------------------------------------
  // Simulate workflow (dry-run)
  // -------------------------------------------------------------------------
  const simulateWorkflow = useCallback(
    async (
      workflowId: string,
      inputs?: Record<string, unknown>,
    ): Promise<SimulationResult | null> => {
      try {
        return (await api.post(
          `/api/v1/workflows/${encodeURIComponent(workflowId)}/simulate`,
          inputs ? { inputs } : {},
        )) as SimulationResult;
      } catch (err) {
        logger.error(`Failed to simulate workflow ${workflowId}:`, err);
        return null;
      }
    },
    [api],
  );

  // -------------------------------------------------------------------------
  // Get workflow status
  // -------------------------------------------------------------------------
  const getWorkflowStatus = useCallback(
    async (workflowId: string): Promise<Record<string, unknown> | null> => {
      try {
        return (await api.get(
          `/api/v1/workflows/${encodeURIComponent(workflowId)}/status`,
        )) as Record<string, unknown>;
      } catch (err) {
        logger.error(`Failed to get workflow status ${workflowId}:`, err);
        return null;
      }
    },
    [api],
  );

  // -------------------------------------------------------------------------
  // Get workflow versions
  // -------------------------------------------------------------------------
  const getVersions = useCallback(
    async (workflowId: string): Promise<WorkflowVersion[]> => {
      try {
        const result = (await api.get(
          `/api/v1/workflows/${encodeURIComponent(workflowId)}/versions`,
        )) as VersionsResponse;
        return result?.versions ?? [];
      } catch (err) {
        logger.error(`Failed to get versions for ${workflowId}:`, err);
        return [];
      }
    },
    [api],
  );

  // -------------------------------------------------------------------------
  // Restore workflow version
  // -------------------------------------------------------------------------
  const restoreVersion = useCallback(
    async (workflowId: string, version: string | number): Promise<boolean> => {
      try {
        await api.post(
          `/api/v1/workflows/${encodeURIComponent(workflowId)}/versions/${version}/restore`,
          {},
        );
        return true;
      } catch (err) {
        logger.error(`Failed to restore version ${version} for ${workflowId}:`, err);
        return false;
      }
    },
    [api],
  );

  // -------------------------------------------------------------------------
  // List templates
  // -------------------------------------------------------------------------
  const fetchTemplates = useCallback(
    async (category?: string): Promise<WorkflowTemplate[]> => {
      try {
        const qs = category ? `?category=${encodeURIComponent(category)}` : '';
        const result = (await api.get(`/api/v1/workflow-templates${qs}`)) as TemplatesResponse;
        const items = result?.templates ?? [];
        setTemplates(items);
        return items;
      } catch (err) {
        logger.error('Failed to fetch workflow templates:', err);
        return [];
      }
    },
    [api],
  );

  // -------------------------------------------------------------------------
  // List approvals
  // -------------------------------------------------------------------------
  const fetchApprovals = useCallback(
    async (workflowId?: string): Promise<ApprovalRequest[]> => {
      try {
        const qs = workflowId ? `?workflow_id=${encodeURIComponent(workflowId)}` : '';
        const result = (await api.get(`/api/v1/workflow-approvals${qs}`)) as ApprovalsResponse;
        return result?.approvals ?? [];
      } catch (err) {
        logger.error('Failed to fetch workflow approvals:', err);
        return [];
      }
    },
    [api],
  );

  // -------------------------------------------------------------------------
  // Resolve approval
  // -------------------------------------------------------------------------
  const resolveApproval = useCallback(
    async (
      requestId: string,
      status: 'approved' | 'rejected',
      notes?: string,
    ): Promise<boolean> => {
      try {
        await api.post(`/api/v1/workflow-approvals/${encodeURIComponent(requestId)}/resolve`, {
          status,
          notes: notes ?? '',
        });
        return true;
      } catch (err) {
        logger.error(`Failed to resolve approval ${requestId}:`, err);
        return false;
      }
    },
    [api],
  );

  // Fetch on mount
  useEffect(() => {
    fetchWorkflows();
    // Only run once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    // State
    workflows,
    templates,
    loading,
    error,

    // CRUD
    fetchWorkflows,
    getWorkflow,
    createWorkflow,
    updateWorkflow,
    deleteWorkflow,

    // Execution
    executeWorkflow,
    simulateWorkflow,
    getWorkflowStatus,

    // Versions
    getVersions,
    restoreVersion,

    // Templates
    fetchTemplates,

    // Approvals
    fetchApprovals,
    resolveApproval,
  };
}

export default useWorkflows;
