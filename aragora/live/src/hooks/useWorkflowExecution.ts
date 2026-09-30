'use client';

/**
 * Workflow Execution hook for monitoring and managing workflow executions.
 *
 * Provides:
 * - Real-time execution monitoring via SSE
 * - Execution management (start, terminate, retry)
 * - Human approval handling
 * - Execution history
 */

import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useApi } from './useApi';
import { useBackend } from '@/components/BackendSelector';
import { logger } from '@/utils/logger';

// Execution types
export type ExecutionStatus =
  'pending' | 'running' | 'paused' | 'waiting_approval' | 'completed' | 'failed' | 'terminated';

export type StepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

export interface ExecutionStep {
  id: string;
  name: string;
  step_type: string;
  status: StepStatus;
  started_at?: string;
  completed_at?: string;
  duration_ms?: number;
  output?: unknown;
  error?: string;
  tokens_used?: number;
  cost_usd?: number;
}

export interface ApprovalRequest {
  id: string;
  execution_id: string;
  step_id: string;
  step_name: string;
  prompt: string;
  context?: Record<string, unknown>;
  requested_at: string;
  deadline?: string;
}

export interface WorkflowExecution {
  id: string;
  workflow_id: string;
  workflow_name: string;
  status: ExecutionStatus;
  started_at: string;
  completed_at?: string;
  duration_ms?: number;
  current_step?: string;
  steps: ExecutionStep[];
  inputs?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  error?: string;
  total_tokens_used?: number;
  total_cost_usd?: number;
  pending_approval?: ApprovalRequest;
}

export interface ExecutionEvent {
  type:
    | 'execution_started'
    | 'execution_completed'
    | 'execution_failed'
    | 'execution_terminated'
    | 'step_started'
    | 'step_completed'
    | 'step_failed'
    | 'approval_required'
    | 'approval_received'
    | 'metrics_update';
  timestamp: string;
  execution_id: string;
  data: Partial<WorkflowExecution> | ExecutionStep | ApprovalRequest;
}

export interface UseWorkflowExecutionOptions {
  /** Whether to auto-connect to the execution stream */
  autoConnect?: boolean;
  /** Callback when an execution completes */
  onExecutionComplete?: (execution: WorkflowExecution) => void;
  /** Callback when an execution fails */
  onExecutionFailed?: (execution: WorkflowExecution) => void;
  /** Callback when approval is required */
  onApprovalRequired?: (request: ApprovalRequest) => void;
}

export interface UseWorkflowExecutionReturn {
  // State
  executions: WorkflowExecution[];
  activeExecutions: WorkflowExecution[];
  recentExecutions: WorkflowExecution[];
  approvalQueue: ApprovalRequest[];
  isConnected: boolean;
  connectionError: string | null;

  // Selected execution
  selectedExecution: WorkflowExecution | null;
  selectExecution: (id: string | null) => void;

  // Execution operations
  startExecution: (workflowId: string, inputs?: Record<string, unknown>) => Promise<string>;
  terminateExecution: (executionId: string) => Promise<void>;
  retryExecution: (executionId: string) => Promise<string>;

  // Approval operations
  resolveApproval: (requestId: string, approved: boolean, notes?: string) => Promise<void>;

  // Data fetching
  loadExecutions: (workflowId?: string) => Promise<void>;
  loadExecution: (executionId: string) => Promise<WorkflowExecution>;

  // Connection management
  connect: () => void;
  disconnect: () => void;
}

/**
 * Hook for workflow execution monitoring and management.
 *
 * @example
 * ```tsx
 * const {
 *   activeExecutions,
 *   approvalQueue,
 *   startExecution,
 *   resolveApproval,
 * } = useWorkflowExecution({
 *   autoConnect: true,
 *   onApprovalRequired: (req) => toast(`Approval needed: ${req.step_name}`),
 * });
 *
 * // Start a workflow
 * const execId = await startExecution('wf_123', { document: 'doc.pdf' });
 *
 * // Approve a step
 * await resolveApproval('approval_456', true, 'Looks good');
 * ```
 */
export function useWorkflowExecution({
  autoConnect = true,
  onExecutionComplete,
  onExecutionFailed,
  onApprovalRequired,
}: UseWorkflowExecutionOptions = {}): UseWorkflowExecutionReturn {
  const { config: backendConfig } = useBackend();
  const api = useApi(backendConfig?.api);

  // State
  const [executions, setExecutions] = useState<WorkflowExecution[]>([]);
  const [approvalQueue, setApprovalQueue] = useState<ApprovalRequest[]>([]);
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  // EventSource ref
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Derived state
  const activeExecutions = useMemo(
    () => executions.filter((e) => ['pending', 'running', 'waiting_approval'].includes(e.status)),
    [executions],
  );

  const recentExecutions = useMemo(
    () =>
      executions
        .filter((e) => ['completed', 'failed', 'terminated'].includes(e.status))
        .sort(
          (a, b) =>
            new Date(b.completed_at || b.started_at).getTime() -
            new Date(a.completed_at || a.started_at).getTime(),
        )
        .slice(0, 20),
    [executions],
  );

  const selectedExecution = useMemo(
    () => executions.find((e) => e.id === selectedExecutionId) || null,
    [executions, selectedExecutionId],
  );

  // Update execution in state
  const updateExecution = useCallback((update: Partial<WorkflowExecution> & { id: string }) => {
    setExecutions((prev) => {
      const idx = prev.findIndex((e) => e.id === update.id);
      if (idx >= 0) {
        const updated = [...prev];
        updated[idx] = { ...updated[idx], ...update };
        return updated;
      }
      // New execution
      return [...prev, update as WorkflowExecution];
    });
  }, []);

  // Handle SSE events
  const handleEvent = useCallback(
    (event: ExecutionEvent) => {
      switch (event.type) {
        case 'execution_started': {
          const execution = event.data as Partial<WorkflowExecution>;
          updateExecution({ id: event.execution_id, ...execution } as WorkflowExecution);
          break;
        }

        case 'execution_completed': {
          const execution = event.data as Partial<WorkflowExecution>;
          updateExecution({
            id: event.execution_id,
            ...execution,
            status: 'completed',
          } as WorkflowExecution);

          const fullExecution = executions.find((e) => e.id === event.execution_id);
          if (fullExecution) {
            onExecutionComplete?.({ ...fullExecution, ...execution });
          }
          break;
        }

        case 'execution_failed': {
          const execution = event.data as Partial<WorkflowExecution>;
          updateExecution({
            id: event.execution_id,
            ...execution,
            status: 'failed',
          } as WorkflowExecution);

          const fullExecution = executions.find((e) => e.id === event.execution_id);
          if (fullExecution) {
            onExecutionFailed?.({ ...fullExecution, ...execution });
          }
          break;
        }

        case 'execution_terminated': {
          updateExecution({ id: event.execution_id, status: 'terminated' } as WorkflowExecution);
          break;
        }

        case 'step_started':
        case 'step_completed':
        case 'step_failed': {
          const step = event.data as ExecutionStep;
          setExecutions((prev) => {
            const idx = prev.findIndex((e) => e.id === event.execution_id);
            if (idx < 0) return prev;

            const updated = [...prev];
            const execution = { ...updated[idx] };
            const stepIdx = execution.steps.findIndex((s) => s.id === step.id);

            if (stepIdx >= 0) {
              execution.steps = [...execution.steps];
              execution.steps[stepIdx] = { ...execution.steps[stepIdx], ...step };
            } else {
              execution.steps = [...execution.steps, step];
            }

            execution.current_step = step.id;
            updated[idx] = execution;
            return updated;
          });
          break;
        }

        case 'approval_required': {
          const request = event.data as ApprovalRequest;
          setApprovalQueue((prev) => {
            const exists = prev.some((r) => r.id === request.id);
            if (exists) return prev;
            return [...prev, request];
          });
          updateExecution({
            id: event.execution_id,
            status: 'waiting_approval',
            pending_approval: request,
          } as WorkflowExecution);
          onApprovalRequired?.(request);
          break;
        }

        case 'approval_received': {
          const request = event.data as ApprovalRequest;
          setApprovalQueue((prev) => prev.filter((r) => r.id !== request.id));
          updateExecution({
            id: event.execution_id,
            status: 'running',
            pending_approval: undefined,
          } as WorkflowExecution);
          break;
        }

        default:
          break;
      }
    },
    [executions, updateExecution, onExecutionComplete, onExecutionFailed, onApprovalRequired],
  );

  // Connect to SSE stream
  const connect = useCallback(() => {
    if (!backendConfig?.api || eventSourceRef.current) return;

    const url = `${backendConfig.api}/api/workflows/executions/stream`;

    try {
      const eventSource = new EventSource(url);
      eventSourceRef.current = eventSource;

      eventSource.onopen = () => {
        setIsConnected(true);
        setConnectionError(null);
      };

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as ExecutionEvent;
          handleEvent(data);
        } catch (error) {
          logger.error('Failed to parse execution event:', error);
        }
      };

      eventSource.onerror = () => {
        setIsConnected(false);
        setConnectionError('Connection lost');
        eventSource.close();
        eventSourceRef.current = null;

        // Attempt reconnect after 5 seconds
        reconnectTimeoutRef.current = setTimeout(() => {
          connect();
        }, 5000);
      };
    } catch (error) {
      setConnectionError(error instanceof Error ? error.message : 'Failed to connect');
    }
  }, [backendConfig?.api, handleEvent]);

  // Disconnect from SSE stream
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    setIsConnected(false);
  }, []);

  // Auto-connect on mount
  useEffect(() => {
    if (autoConnect) {
      connect();
    }

    return () => {
      disconnect();
    };
  }, [autoConnect, connect, disconnect]);

  // Start a workflow execution
  const startExecution = useCallback(
    async (workflowId: string, inputs?: Record<string, unknown>): Promise<string> => {
      const response = (await api.post(`/api/workflows/${workflowId}/execute`, { inputs })) as {
        execution_id: string;
      };

      return response.execution_id;
    },
    [api],
  );

  // Terminate an execution
  const terminateExecution = useCallback(
    async (executionId: string): Promise<void> => {
      await api.post(`/api/workflows/executions/${executionId}/terminate`);
    },
    [api],
  );

  // Retry a failed execution
  const retryExecution = useCallback(
    async (executionId: string): Promise<string> => {
      const response = (await api.post(`/api/workflows/executions/${executionId}/retry`)) as {
        execution_id: string;
      };

      return response.execution_id;
    },
    [api],
  );

  // Resolve an approval request
  const resolveApproval = useCallback(
    async (requestId: string, approved: boolean, notes?: string): Promise<void> => {
      await api.post(`/api/workflow-approvals/${requestId}/resolve`, {
        status: approved ? 'approved' : 'rejected',
        notes,
      });

      // Remove from local queue
      setApprovalQueue((prev) => prev.filter((r) => r.id !== requestId));
    },
    [api],
  );

  // Load executions (optionally filtered by workflow)
  const loadExecutions = useCallback(
    async (workflowId?: string): Promise<void> => {
      const params = workflowId ? `?workflow_id=${workflowId}` : '';
      const response = (await api.get(`/api/workflows/executions${params}`)) as {
        executions: WorkflowExecution[];
      };

      setExecutions(response.executions || []);
    },
    [api],
  );

  // Load a specific execution
  const loadExecution = useCallback(
    async (executionId: string): Promise<WorkflowExecution> => {
      const response = (await api.get(
        `/api/workflows/executions/${executionId}`,
      )) as WorkflowExecution;

      // Update in local state
      updateExecution(response);

      return response;
    },
    [api, updateExecution],
  );

  // Select an execution
  const selectExecution = useCallback((id: string | null) => {
    setSelectedExecutionId(id);
  }, []);

  return {
    // State
    executions,
    activeExecutions,
    recentExecutions,
    approvalQueue,
    isConnected,
    connectionError,

    // Selected
    selectedExecution,
    selectExecution,

    // Operations
    startExecution,
    terminateExecution,
    retryExecution,
    resolveApproval,
    loadExecutions,
    loadExecution,

    // Connection
    connect,
    disconnect,
  };
}

export default useWorkflowExecution;
