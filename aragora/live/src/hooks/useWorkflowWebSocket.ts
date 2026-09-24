'use client';

/**
 * Workflow WebSocket hook for real-time workflow execution updates.
 *
 * Provides:
 * - Workflow execution status updates
 * - Step progress tracking
 * - Execution logs streaming
 * - Approval request notifications
 */

import { useState, useCallback, useMemo } from 'react';
import { useWebSocketBase, WebSocketConnectionStatus } from './useWebSocketBase';
import { useBackend } from '@/components/BackendSelector';

// Event types from the workflow stream
export type WorkflowEventType =
  | 'execution_started'
  | 'execution_completed'
  | 'execution_failed'
  | 'execution_cancelled'
  | 'step_started'
  | 'step_completed'
  | 'step_failed'
  | 'step_skipped'
  | 'approval_required'
  | 'approval_received'
  | 'log_entry'
  | 'variable_updated';

export interface WorkflowExecutionState {
  id: string;
  workflow_id: string;
  workflow_name: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'awaiting_approval';
  current_step?: string;
  progress: number;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  variables?: Record<string, unknown>;
}

export interface WorkflowStepState {
  id: string;
  execution_id: string;
  name: string;
  type: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  progress: number;
  started_at?: string;
  completed_at?: string;
  duration_ms?: number;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  error_message?: string;
}

export interface WorkflowApprovalRequest {
  id: string;
  execution_id: string;
  step_id: string;
  step_name: string;
  requested_at: string;
  requested_by?: string;
  reason?: string;
  expires_at?: string;
}

export interface WorkflowLogEntry {
  timestamp: string;
  level: 'debug' | 'info' | 'warn' | 'error';
  step_id?: string;
  message: string;
  data?: Record<string, unknown>;
}

export interface WorkflowEvent {
  type: WorkflowEventType;
  timestamp: string;
  execution_id: string;
  seq?: number;
  data: WorkflowExecutionState | WorkflowStepState | WorkflowApprovalRequest | WorkflowLogEntry;
}

export interface UseWorkflowWebSocketOptions {
  /** Execution ID to monitor (if not provided, monitors all executions) */
  executionId?: string;
  /** Whether the connection is enabled */
  enabled?: boolean;
  /** Whether to automatically reconnect on disconnection */
  autoReconnect?: boolean;
  /** Callback when execution status changes */
  onExecutionUpdate?: (execution: WorkflowExecutionState) => void;
  /** Callback when step status changes */
  onStepUpdate?: (step: WorkflowStepState) => void;
  /** Callback when approval is required */
  onApprovalRequired?: (approval: WorkflowApprovalRequest) => void;
  /** Callback when a log entry is received */
  onLogEntry?: (log: WorkflowLogEntry) => void;
}

export interface UseWorkflowWebSocketReturn {
  /** Current WebSocket connection status */
  status: WebSocketConnectionStatus;
  /** Whether connected to the workflow stream */
  isConnected: boolean;
  /** Connection error message if any */
  error: string | null;
  /** Current reconnection attempt */
  reconnectAttempt: number;
  /** Current execution state (if monitoring a specific execution) */
  execution: WorkflowExecutionState | null;
  /** Current step states */
  steps: WorkflowStepState[];
  /** Pending approval requests */
  approvals: WorkflowApprovalRequest[];
  /** Recent log entries (last 100) */
  logs: WorkflowLogEntry[];
  /** Manually reconnect */
  reconnect: () => void;
  /** Manually disconnect */
  disconnect: () => void;
  /** Send approval decision */
  sendApproval: (approvalId: string, approved: boolean, comment?: string) => void;
  /** Cancel execution */
  cancelExecution: (executionId: string) => void;
}

/**
 * Hook for connecting to the Workflow WebSocket stream.
 *
 * @example
 * ```tsx
 * const {
 *   status,
 *   isConnected,
 *   execution,
 *   steps,
 *   logs,
 * } = useWorkflowWebSocket({
 *   executionId: 'exec-123',
 *   enabled: true,
 *   onApprovalRequired: (approval) => {
 *     toast(`Approval required: ${approval.step_name}`);
 *   },
 * });
 * ```
 */
export function useWorkflowWebSocket({
  executionId,
  enabled = true,
  autoReconnect = true,
  onExecutionUpdate,
  onStepUpdate,
  onApprovalRequired,
  onLogEntry,
}: UseWorkflowWebSocketOptions = {}): UseWorkflowWebSocketReturn {
  const { config: backendConfig } = useBackend();

  // State
  const [execution, setExecution] = useState<WorkflowExecutionState | null>(null);
  const [steps, setSteps] = useState<WorkflowStepState[]>([]);
  const [approvals, setApprovals] = useState<WorkflowApprovalRequest[]>([]);
  const [logs, setLogs] = useState<WorkflowLogEntry[]>([]);

  // Build WebSocket URL
  const wsUrl = useMemo(() => {
    if (!backendConfig?.api) return '';
    const baseUrl = backendConfig.api.replace(/^http/, 'ws');
    return executionId
      ? `${baseUrl}/api/workflows/executions/${executionId}/stream`
      : `${baseUrl}/api/workflows/stream`;
  }, [backendConfig?.api, executionId]);

  // Handle incoming events
  const handleEvent = useCallback(
    (event: WorkflowEvent) => {
      switch (event.type) {
        case 'execution_started':
        case 'execution_completed':
        case 'execution_failed':
        case 'execution_cancelled': {
          const executionData = event.data as WorkflowExecutionState;
          setExecution(executionData);
          onExecutionUpdate?.(executionData);
          break;
        }

        case 'step_started':
        case 'step_completed':
        case 'step_failed':
        case 'step_skipped': {
          const step = event.data as WorkflowStepState;
          setSteps((prev) => {
            const idx = prev.findIndex((s) => s.id === step.id);
            if (idx >= 0) {
              const updated = [...prev];
              updated[idx] = step;
              return updated;
            }
            return [...prev, step];
          });
          onStepUpdate?.(step);
          break;
        }

        case 'approval_required': {
          const approval = event.data as WorkflowApprovalRequest;
          setApprovals((prev) => [...prev, approval]);
          onApprovalRequired?.(approval);
          break;
        }

        case 'approval_received': {
          const approval = event.data as WorkflowApprovalRequest;
          setApprovals((prev) => prev.filter((a) => a.id !== approval.id));
          break;
        }

        case 'log_entry': {
          const log = event.data as WorkflowLogEntry;
          setLogs((prev) => [...prev.slice(-99), log]); // Keep last 100
          onLogEntry?.(log);
          break;
        }

        case 'variable_updated': {
          // Update execution variables
          setExecution((prev) => {
            if (!prev) return prev;
            return {
              ...prev,
              variables: {
                ...prev.variables,
                ...(event.data as unknown as Record<string, unknown>),
              },
            };
          });
          break;
        }

        default:
          break;
      }
    },
    [onExecutionUpdate, onStepUpdate, onApprovalRequired, onLogEntry],
  );

  // Use base WebSocket hook
  const { status, error, isConnected, reconnectAttempt, send, reconnect, disconnect } =
    useWebSocketBase<WorkflowEvent>({
      wsUrl,
      enabled: enabled && !!wsUrl,
      autoReconnect,
      subscribeMessage: executionId
        ? { type: 'subscribe', execution_id: executionId }
        : { type: 'subscribe', channels: ['executions'] },
      onEvent: handleEvent,
      logPrefix: '[Workflow]',
    });

  // Send approval decision
  const sendApproval = useCallback(
    (approvalId: string, approved: boolean, comment?: string) => {
      send({ type: 'approval_response', approval_id: approvalId, approved, comment });
    },
    [send],
  );

  // Cancel execution
  const cancelExecution = useCallback(
    (execId: string) => {
      send({ type: 'cancel_execution', execution_id: execId });
    },
    [send],
  );

  return {
    status,
    isConnected,
    error,
    reconnectAttempt,
    execution,
    steps,
    approvals,
    logs,
    reconnect,
    disconnect,
    sendApproval,
    cancelExecution,
  };
}

export default useWorkflowWebSocket;
