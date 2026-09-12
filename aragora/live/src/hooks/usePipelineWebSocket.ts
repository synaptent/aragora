'use client';

/**
 * Pipeline WebSocket hook for real-time pipeline stage updates.
 *
 * Provides:
 * - Stage completion notifications
 * - Node-by-node progressive rendering
 * - Transition approval gate events
 * - Pipeline lifecycle events
 */

import { useState, useCallback, useMemo } from 'react';
import { useWebSocketBase, type WebSocketConnectionStatus } from './useWebSocketBase';
import { useBackend } from '@/components/BackendSelector';

export type PipelineEventType =
  | 'pipeline_started'
  | 'pipeline_stage_started'
  | 'pipeline_stage_completed'
  | 'pipeline_graph_updated'
  | 'pipeline_goal_extracted'
  | 'pipeline_workflow_generated'
  | 'pipeline_step_progress'
  | 'pipeline_node_added'
  | 'pipeline_node_status'
  | 'pipeline_transition_pending'
  | 'pipeline_completed'
  | 'pipeline_failed';

export interface PipelineStageEvent {
  stage: string;
  summary?: Record<string, unknown>;
  config?: Record<string, unknown>;
}

export interface PipelineNodeEvent {
  stage: string;
  node_id: string;
  node_type: string;
  label: string;
  added_at: number;
}

export interface PipelineTransitionEvent {
  from_stage: string;
  to_stage: string;
  confidence: number;
  ai_rationale: string;
  pending_at: number;
}

export interface PipelineGraphEvent {
  graph: { nodes: Array<Record<string, unknown>>; edges: Array<Record<string, unknown>> };
}

export interface PipelineNodeStatusEvent {
  node_id: string;
  status: string;
  elapsed_ms?: number;
  output_preview?: string;
  agent?: string;
}

export interface PipelineStepProgressEvent {
  step: string;
  progress: number;
  completed?: number;
  total?: number;
  current_task?: string;
}

export interface PipelineCompletionEvent {
  receipt?: Record<string, unknown>;
  error?: string;
}

export interface PipelineStreamEvent {
  type: PipelineEventType;
  timestamp: number;
  data: { pipeline_id: string } & Record<string, unknown>;
}

export interface UsePipelineWebSocketOptions {
  /** Pipeline ID to monitor */
  pipelineId?: string;
  /** Whether the connection is enabled */
  enabled?: boolean;
  /** Callback when a stage starts */
  onStageStarted?: (event: PipelineStageEvent) => void;
  /** Callback when a stage completes */
  onStageCompleted?: (event: PipelineStageEvent) => void;
  /** Callback when a node is added (progressive rendering) */
  onNodeAdded?: (event: PipelineNodeEvent) => void;
  /** Callback when a transition approval is pending */
  onTransitionPending?: (event: PipelineTransitionEvent) => void;
  /** Callback when a node's execution status changes */
  onNodeStatus?: (event: PipelineNodeStatusEvent) => void;
  /** Callback when step progress is reported */
  onStepProgress?: (event: PipelineStepProgressEvent) => void;
  /** Callback when the full graph is updated */
  onGraphUpdated?: (event: PipelineGraphEvent) => void;
  /** Callback when the pipeline completes */
  onCompleted?: (event: PipelineCompletionEvent) => void;
  /** Callback when the pipeline fails */
  onFailed?: (error: string) => void;
}

export interface UsePipelineWebSocketReturn {
  status: WebSocketConnectionStatus;
  isConnected: boolean;
  error: string | null;
  /** Stages that have been completed */
  completedStages: string[];
  /** Nodes added during streaming */
  streamedNodes: PipelineNodeEvent[];
  /** Latest node status updates keyed by node_id */
  nodeStatuses: Record<string, PipelineNodeStatusEvent>;
  /** Pending transition gates */
  pendingTransitions: PipelineTransitionEvent[];
  /** Whether the pipeline run is finished */
  isComplete: boolean;
  /** Manually reconnect */
  reconnect: () => void;
  /** Manually disconnect */
  disconnect: () => void;
  /** Request history replay */
  requestHistory: (limit?: number) => void;
}

export function usePipelineWebSocket({
  pipelineId,
  enabled = true,
  onStageStarted,
  onStageCompleted,
  onNodeAdded,
  onNodeStatus,
  onTransitionPending,
  onStepProgress,
  onGraphUpdated,
  onCompleted,
  onFailed,
}: UsePipelineWebSocketOptions = {}): UsePipelineWebSocketReturn {
  const { config: backendConfig } = useBackend();

  const [completedStages, setCompletedStages] = useState<string[]>([]);
  const [streamedNodes, setStreamedNodes] = useState<PipelineNodeEvent[]>([]);
  const [nodeStatuses, setNodeStatuses] = useState<Record<string, PipelineNodeStatusEvent>>({});
  const [pendingTransitions, setPendingTransitions] = useState<PipelineTransitionEvent[]>([]);
  const [isComplete, setIsComplete] = useState(false);

  const wsUrl = useMemo(() => {
    if (!backendConfig?.api || !pipelineId) return '';
    const baseUrl = backendConfig.api.replace(/^http/, 'ws');
    return `${baseUrl}/ws/pipeline?pipeline_id=${encodeURIComponent(pipelineId)}`;
  }, [backendConfig?.api, pipelineId]);

  const handleEvent = useCallback(
    (event: PipelineStreamEvent) => {
      const data = event.data;
      switch (event.type) {
        case 'pipeline_stage_started':
          onStageStarted?.({
            stage: data.stage as string,
            config: data.config as Record<string, unknown>,
          });
          break;

        case 'pipeline_stage_completed':
          setCompletedStages((prev) => {
            const stage = data.stage as string;
            return prev.includes(stage) ? prev : [...prev, stage];
          });
          onStageCompleted?.({
            stage: data.stage as string,
            summary: data.summary as Record<string, unknown>,
          });
          break;

        case 'pipeline_node_added': {
          const nodeEvent: PipelineNodeEvent = {
            stage: data.stage as string,
            node_id: data.node_id as string,
            node_type: data.node_type as string,
            label: data.label as string,
            added_at: data.added_at as number,
          };
          setStreamedNodes((prev) => [...prev, nodeEvent]);
          onNodeAdded?.(nodeEvent);
          break;
        }

        case 'pipeline_transition_pending': {
          const transEvent: PipelineTransitionEvent = {
            from_stage: data.from_stage as string,
            to_stage: data.to_stage as string,
            confidence: data.confidence as number,
            ai_rationale: data.ai_rationale as string,
            pending_at: data.pending_at as number,
          };
          setPendingTransitions((prev) => [...prev, transEvent]);
          onTransitionPending?.(transEvent);
          break;
        }

        case 'pipeline_node_status': {
          const nodeStatusEvent: PipelineNodeStatusEvent = {
            node_id: data.node_id as string,
            status: data.status as string,
            elapsed_ms: data.elapsed_ms as number | undefined,
            output_preview: data.output_preview as string | undefined,
            agent: data.agent as string | undefined,
          };
          setNodeStatuses((prev) => ({ ...prev, [nodeStatusEvent.node_id]: nodeStatusEvent }));
          onNodeStatus?.(nodeStatusEvent);
          break;
        }

        case 'pipeline_step_progress':
          onStepProgress?.({
            step: data.step as string,
            progress: data.progress as number,
            completed: data.completed as number | undefined,
            total: data.total as number | undefined,
            current_task: data.current_task as string | undefined,
          });
          break;

        case 'pipeline_graph_updated':
          onGraphUpdated?.({ graph: data.graph as PipelineGraphEvent['graph'] });
          break;

        case 'pipeline_completed':
          setIsComplete(true);
          onCompleted?.({ receipt: data.receipt as Record<string, unknown> });
          break;

        case 'pipeline_failed':
          setIsComplete(true);
          onFailed?.(data.error as string);
          break;

        default:
          break;
      }
    },
    [
      onStageStarted,
      onStageCompleted,
      onNodeAdded,
      onNodeStatus,
      onTransitionPending,
      onStepProgress,
      onGraphUpdated,
      onCompleted,
      onFailed,
    ],
  );

  const { status, error, isConnected, reconnect, disconnect, send } =
    useWebSocketBase<PipelineStreamEvent>({
      wsUrl,
      enabled: enabled && !!wsUrl,
      autoReconnect: true,
      onEvent: handleEvent,
      logPrefix: '[Pipeline]',
    });

  const requestHistory = useCallback(
    (limit = 100) => {
      send({ type: 'get_history', limit });
    },
    [send],
  );

  return {
    status,
    isConnected,
    error,
    completedStages,
    streamedNodes,
    nodeStatuses,
    pendingTransitions,
    isComplete,
    reconnect,
    disconnect,
    requestHistory,
  };
}

export default usePipelineWebSocket;
