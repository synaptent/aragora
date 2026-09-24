'use client';

/**
 * Control Plane WebSocket hook for real-time agent orchestration updates.
 *
 * Provides:
 * - Agent registration/unregistration events
 * - Agent status changes
 * - Task lifecycle events (submitted, claimed, completed, failed)
 * - System health and metrics updates
 */

import { useState, useCallback, useMemo } from 'react';
import { useWebSocketBase, WebSocketConnectionStatus } from './useWebSocketBase';
import { useBackend } from '@/components/BackendSelector';
import { CONTROL_PLANE_WS_URL } from '@/config';
import { logger } from '@/utils/logger';

// Event types from the control plane stream (matches backend ControlPlaneEventType)
export type ControlPlaneEventType =
  | 'connected'
  | 'disconnected'
  | 'agent_registered'
  | 'agent_unregistered'
  | 'agent_status_changed'
  | 'agent_heartbeat'
  | 'agent_timeout'
  | 'task_submitted'
  | 'task_claimed'
  | 'task_started'
  | 'task_completed'
  | 'task_failed'
  | 'task_cancelled'
  | 'task_retrying'
  | 'task_dead_lettered'
  | 'health_update'
  | 'metrics_update'
  | 'scheduler_stats'
  // Deliberation events
  | 'deliberation_started'
  | 'deliberation_progress'
  | 'deliberation_round'
  | 'deliberation_vote'
  | 'deliberation_consensus'
  | 'deliberation_completed'
  | 'deliberation_failed'
  | 'deliberation_sla_warning'
  | 'error';

// Agent state matching backend schema
export interface AgentState {
  id: string;
  status: 'idle' | 'busy' | 'offline' | 'error' | 'working' | 'rate_limited';
  capabilities: string[];
  model: string;
  provider: string;
  current_task_id?: string;
  last_heartbeat?: string;
  metadata?: Record<string, unknown>;
  // Display-oriented fields (optional, for UI compatibility)
  name?: string;
  current_task?: string;
  requests_today?: number;
  tokens_used?: number;
  last_active?: string;
  error_message?: string;
  current_job_id?: string;
}

// Task state matching backend schema
export interface TaskState {
  id: string;
  task_type: string;
  status:
    'pending' | 'claimed' | 'running' | 'completed' | 'failed' | 'cancelled' | 'dead_lettered';
  priority: 'low' | 'normal' | 'high' | 'critical';
  assigned_agent_id?: string;
  required_capabilities: string[];
  payload?: Record<string, unknown>;
  result_summary?: string;
  error?: string;
  retries_left?: number;
  created_at?: string;
  started_at?: string;
  completed_at?: string;
}

// Backwards compatible alias - use TaskState for new code
export type JobState = TaskState & {
  type?: string;
  name?: string;
  progress?: number;
  phase?: string;
  document_count?: number;
  documents_processed?: number;
  findings_count?: number;
  agents_assigned?: string[];
  error_message?: string;
};

// System health/metrics from backend
export interface SystemHealth {
  status: 'healthy' | 'degraded' | 'unhealthy';
  agents: Record<string, AgentState>;
  timestamp?: number;
}

export interface SchedulerStats {
  pending_tasks: number;
  running_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  agents_registered: number;
  agents_idle: number;
  agents_busy: number;
}

// Deliberation state for tracking active debates
export interface DeliberationState {
  id: string;
  question: string;
  status: 'started' | 'in_progress' | 'consensus' | 'completed' | 'failed';
  agents: string[];
  current_round: number;
  total_rounds: number;
  progress_pct: number;
  consensus_reached?: boolean;
  confidence?: number;
  winner?: string;
  sla_warning?: boolean;
  sla_level?: 'warning' | 'critical' | 'violated';
  started_at?: number;
  completed_at?: number;
  duration_seconds?: number;
  votes?: Record<string, string>;
}

// Event payload from the backend WebSocket
export interface ControlPlaneEvent {
  type: ControlPlaneEventType;
  timestamp: number;
  data: Record<string, unknown>;
}

export interface UseControlPlaneWebSocketOptions {
  /** Whether the connection is enabled */
  enabled?: boolean;
  /** Whether to automatically reconnect on disconnection */
  autoReconnect?: boolean;
  /** Custom WebSocket URL (overrides default) */
  wsUrl?: string;
  /** Callback when agent is registered */
  onAgentRegistered?: (agentId: string, data: Record<string, unknown>) => void;
  /** Callback when agent is unregistered */
  onAgentUnregistered?: (agentId: string, reason: string) => void;
  /** Callback when agent status changes */
  onAgentStatusChanged?: (agentId: string, oldStatus: string, newStatus: string) => void;
  /** Callback when task is submitted */
  onTaskSubmitted?: (taskId: string, data: Record<string, unknown>) => void;
  /** Callback when task is claimed */
  onTaskClaimed?: (taskId: string, agentId: string) => void;
  /** Callback when task is completed */
  onTaskCompleted?: (taskId: string, agentId: string, result?: string) => void;
  /** Callback when task fails */
  onTaskFailed?: (taskId: string, agentId: string, error: string) => void;
  /** Callback when health updates */
  onHealthUpdate?: (health: SystemHealth) => void;
  /** Callback when scheduler stats update */
  onSchedulerStats?: (stats: SchedulerStats) => void;
  /** Callback when deliberation starts */
  onDeliberationStarted?: (taskId: string, data: Record<string, unknown>) => void;
  /** Callback when deliberation progresses */
  onDeliberationProgress?: (taskId: string, data: Record<string, unknown>) => void;
  /** Callback when deliberation reaches consensus */
  onDeliberationConsensus?: (taskId: string, reached: boolean, confidence: number) => void;
  /** Callback when deliberation completes */
  onDeliberationCompleted?: (
    taskId: string,
    success: boolean,
    data: Record<string, unknown>,
  ) => void;
  /** Callback when deliberation SLA warning */
  onDeliberationSlaWarning?: (taskId: string, level: string, data: Record<string, unknown>) => void;
  /** Callback for any event */
  onEvent?: (event: ControlPlaneEvent) => void;
}

export interface UseControlPlaneWebSocketReturn {
  /** Current WebSocket connection status */
  status: WebSocketConnectionStatus;
  /** Whether connected to the control plane stream */
  isConnected: boolean;
  /** Connection error message if any */
  error: string | null;
  /** Current reconnection attempt */
  reconnectAttempt: number;
  /** Current state of all agents (by ID) */
  agents: Map<string, AgentState>;
  /** Current state of all tasks (by ID) */
  tasks: Map<string, TaskState>;
  /** Current system health */
  health: SystemHealth | null;
  /** Current scheduler stats */
  schedulerStats: SchedulerStats | null;
  /** Active deliberations (by ID) */
  deliberations: Map<string, DeliberationState>;
  /** Recent events (last 100) */
  recentEvents: ControlPlaneEvent[];
  /** Manually reconnect */
  reconnect: () => void;
  /** Manually disconnect */
  disconnect: () => void;
  /** Send ping to server */
  sendPing: () => void;
}

const DEFAULT_SCHEDULER_STATS: SchedulerStats = {
  pending_tasks: 0,
  running_tasks: 0,
  completed_tasks: 0,
  failed_tasks: 0,
  agents_registered: 0,
  agents_idle: 0,
  agents_busy: 0,
};

/**
 * Hook for connecting to the Control Plane WebSocket stream.
 *
 * @example
 * ```tsx
 * const {
 *   status,
 *   isConnected,
 *   agents,
 *   tasks,
 *   health,
 *   schedulerStats,
 * } = useControlPlaneWebSocket({
 *   enabled: true,
 *   onTaskCompleted: (taskId, agentId, result) => {
 *     toast(`Task ${taskId} completed by ${agentId}`);
 *   },
 * });
 * ```
 */
export function useControlPlaneWebSocket({
  enabled = true,
  autoReconnect = true,
  wsUrl: customWsUrl,
  onAgentRegistered,
  onAgentUnregistered,
  onAgentStatusChanged,
  onTaskSubmitted,
  onTaskClaimed,
  onTaskCompleted,
  onTaskFailed,
  onHealthUpdate,
  onSchedulerStats,
  onDeliberationStarted,
  onDeliberationProgress,
  onDeliberationConsensus,
  onDeliberationCompleted,
  onDeliberationSlaWarning,
  onEvent,
}: UseControlPlaneWebSocketOptions = {}): UseControlPlaneWebSocketReturn {
  const { config: backendConfig } = useBackend();

  // State for agents, tasks, health, deliberations, and events
  const [agents, setAgents] = useState<Map<string, AgentState>>(new Map());
  const [tasks, setTasks] = useState<Map<string, TaskState>>(new Map());
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [schedulerStats, setSchedulerStats] = useState<SchedulerStats | null>(null);
  const [deliberations, setDeliberations] = useState<Map<string, DeliberationState>>(new Map());
  const [recentEvents, setRecentEvents] = useState<ControlPlaneEvent[]>([]);

  // Build WebSocket URL - use custom URL, backend config, or default
  const wsUrl = useMemo(() => {
    if (customWsUrl) return customWsUrl;
    // Check for control plane WebSocket URL in backend config
    const config = backendConfig as { controlPlaneWs?: string } | undefined;
    if (config?.controlPlaneWs) return config.controlPlaneWs;
    return CONTROL_PLANE_WS_URL;
  }, [customWsUrl, backendConfig]);

  // Handle incoming events
  const handleEvent = useCallback(
    (event: ControlPlaneEvent) => {
      // Add to recent events
      setRecentEvents((prev) => [event, ...prev].slice(0, 100));

      // Call generic event handler
      onEvent?.(event);

      const { data } = event;

      switch (event.type) {
        case 'connected':
          // Connection confirmed
          break;

        case 'agent_registered': {
          const agentId = data.agent_id as string;
          const newAgent: AgentState = {
            id: agentId,
            status: 'idle',
            capabilities: (data.capabilities as string[]) || [],
            model: (data.model as string) || 'unknown',
            provider: (data.provider as string) || 'unknown',
          };
          setAgents((prev) => new Map(prev).set(agentId, newAgent));
          onAgentRegistered?.(agentId, data);
          break;
        }

        case 'agent_unregistered': {
          const agentId = data.agent_id as string;
          const reason = (data.reason as string) || '';
          setAgents((prev) => {
            const updated = new Map(prev);
            updated.delete(agentId);
            return updated;
          });
          onAgentUnregistered?.(agentId, reason);
          break;
        }

        case 'agent_status_changed': {
          const agentId = data.agent_id as string;
          const oldStatus = data.old_status as string;
          const newStatus = data.new_status as string;
          setAgents((prev) => {
            const existing = prev.get(agentId);
            if (existing) {
              const updated = new Map(prev);
              updated.set(agentId, { ...existing, status: newStatus as AgentState['status'] });
              return updated;
            }
            return prev;
          });
          onAgentStatusChanged?.(agentId, oldStatus, newStatus);
          break;
        }

        case 'task_submitted': {
          const taskId = data.task_id as string;
          const newTask: TaskState = {
            id: taskId,
            task_type: (data.task_type as string) || 'unknown',
            status: 'pending',
            priority: (data.priority as TaskState['priority']) || 'normal',
            required_capabilities: (data.required_capabilities as string[]) || [],
          };
          setTasks((prev) => new Map(prev).set(taskId, newTask));
          onTaskSubmitted?.(taskId, data);
          break;
        }

        case 'task_claimed': {
          const taskId = data.task_id as string;
          const agentId = data.agent_id as string;
          setTasks((prev) => {
            const existing = prev.get(taskId);
            if (existing) {
              const updated = new Map(prev);
              updated.set(taskId, { ...existing, status: 'claimed', assigned_agent_id: agentId });
              return updated;
            }
            return prev;
          });
          onTaskClaimed?.(taskId, agentId);
          break;
        }

        case 'task_completed': {
          const taskId = data.task_id as string;
          const agentId = (data.agent_id as string) || 'unknown';
          const resultSummary = data.result_summary as string | undefined;
          setTasks((prev) => {
            const existing = prev.get(taskId);
            if (existing) {
              const updated = new Map(prev);
              updated.set(taskId, {
                ...existing,
                status: 'completed',
                assigned_agent_id: agentId,
                result_summary: resultSummary,
              });
              return updated;
            }
            return prev;
          });
          onTaskCompleted?.(taskId, agentId, resultSummary);
          break;
        }

        case 'task_failed': {
          const taskId = data.task_id as string;
          const agentId = (data.agent_id as string) || 'unknown';
          const error = (data.error as string) || 'Unknown error';
          setTasks((prev) => {
            const existing = prev.get(taskId);
            if (existing) {
              const updated = new Map(prev);
              updated.set(taskId, {
                ...existing,
                status: 'failed',
                assigned_agent_id: agentId,
                error,
                retries_left: data.retries_left as number | undefined,
              });
              return updated;
            }
            return prev;
          });
          onTaskFailed?.(taskId, agentId, error);
          break;
        }

        case 'task_dead_lettered': {
          const taskId = data.task_id as string;
          setTasks((prev) => {
            const existing = prev.get(taskId);
            if (existing) {
              const updated = new Map(prev);
              updated.set(taskId, {
                ...existing,
                status: 'dead_lettered',
                error: (data.reason as string) || 'Moved to dead letter queue',
              });
              return updated;
            }
            return prev;
          });
          break;
        }

        case 'health_update': {
          const newHealth: SystemHealth = {
            status: (data.status as SystemHealth['status']) || 'healthy',
            agents: (data.agents as Record<string, AgentState>) || {},
            timestamp: event.timestamp,
          };
          setHealth(newHealth);
          onHealthUpdate?.(newHealth);
          break;
        }

        case 'scheduler_stats': {
          const stats = data as unknown as SchedulerStats;
          setSchedulerStats(stats);
          onSchedulerStats?.(stats);
          break;
        }

        // Deliberation events
        case 'deliberation_started': {
          const taskId = data.task_id as string;
          const newDelib: DeliberationState = {
            id: taskId,
            question: (data.question_preview as string) || '',
            status: 'started',
            agents: (data.agents as string[]) || [],
            current_round: 0,
            total_rounds: (data.total_rounds as number) || 0,
            progress_pct: 0,
            started_at: event.timestamp,
          };
          setDeliberations((prev) => new Map(prev).set(taskId, newDelib));
          onDeliberationStarted?.(taskId, data);
          break;
        }

        case 'deliberation_round': {
          const taskId = data.task_id as string;
          setDeliberations((prev) => {
            const existing = prev.get(taskId);
            if (existing) {
              return new Map(prev).set(taskId, {
                ...existing,
                status: 'in_progress',
                current_round: (data.round as number) || existing.current_round,
                total_rounds: (data.total_rounds as number) || existing.total_rounds,
                progress_pct: (data.progress_pct as number) || 0,
              });
            }
            return prev;
          });
          onDeliberationProgress?.(taskId, data);
          break;
        }

        case 'deliberation_progress': {
          const taskId = data.task_id as string;
          onDeliberationProgress?.(taskId, data);
          break;
        }

        case 'deliberation_consensus': {
          const taskId = data.task_id as string;
          const reached = data.reached as boolean;
          const confidence = (data.confidence as number) || 0;
          setDeliberations((prev) => {
            const existing = prev.get(taskId);
            if (existing) {
              return new Map(prev).set(taskId, {
                ...existing,
                status: reached ? 'consensus' : 'in_progress',
                consensus_reached: reached,
                confidence,
              });
            }
            return prev;
          });
          onDeliberationConsensus?.(taskId, reached, confidence);
          break;
        }

        case 'deliberation_completed': {
          const taskId = data.task_id as string;
          setDeliberations((prev) => {
            const existing = prev.get(taskId);
            if (existing) {
              return new Map(prev).set(taskId, {
                ...existing,
                status: (data.success as boolean) ? 'completed' : 'failed',
                consensus_reached: data.consensus_reached as boolean,
                confidence: data.confidence as number,
                winner: data.winner as string | undefined,
                duration_seconds: data.duration_seconds as number,
                completed_at: event.timestamp,
              });
            }
            return prev;
          });
          onDeliberationCompleted?.(taskId, data.success as boolean, data);
          break;
        }

        case 'deliberation_failed': {
          const taskId = data.task_id as string;
          setDeliberations((prev) => {
            const existing = prev.get(taskId);
            if (existing) {
              return new Map(prev).set(taskId, {
                ...existing,
                status: 'failed',
                completed_at: event.timestamp,
              });
            }
            return prev;
          });
          onDeliberationCompleted?.(taskId, false, data);
          break;
        }

        case 'deliberation_sla_warning': {
          const taskId = data.task_id as string;
          const level = (data.level as string) || 'warning';
          setDeliberations((prev) => {
            const existing = prev.get(taskId);
            if (existing) {
              return new Map(prev).set(taskId, {
                ...existing,
                sla_warning: true,
                sla_level: level as 'warning' | 'critical' | 'violated',
              });
            }
            return prev;
          });
          onDeliberationSlaWarning?.(taskId, level, data);
          break;
        }

        case 'deliberation_vote': {
          const taskId = data.task_id as string;
          setDeliberations((prev) => {
            const existing = prev.get(taskId);
            if (existing) {
              const votes = { ...(existing.votes || {}) };
              votes[data.agent as string] = data.choice as string;
              return new Map(prev).set(taskId, { ...existing, votes });
            }
            return prev;
          });
          break;
        }

        case 'error':
          // Log errors but don't disrupt state
          logger.error('[ControlPlane] Error event:', data.error, data.context);
          break;

        default:
          // Unknown event type - log for debugging

          logger.debug('[ControlPlane] Unknown event type:', event.type);
          break;
      }
    },
    [
      onEvent,
      onAgentRegistered,
      onAgentUnregistered,
      onAgentStatusChanged,
      onTaskSubmitted,
      onTaskClaimed,
      onTaskCompleted,
      onTaskFailed,
      onHealthUpdate,
      onSchedulerStats,
      onDeliberationStarted,
      onDeliberationProgress,
      onDeliberationConsensus,
      onDeliberationCompleted,
      onDeliberationSlaWarning,
    ],
  );

  // Use base WebSocket hook
  const { status, error, isConnected, reconnectAttempt, send, reconnect, disconnect } =
    useWebSocketBase<ControlPlaneEvent>({
      wsUrl,
      enabled: enabled && !!wsUrl,
      autoReconnect,
      onEvent: handleEvent,
      logPrefix: '[ControlPlane]',
    });

  // Send ping to server
  const sendPing = useCallback(() => {
    send({ type: 'ping' });
  }, [send]);

  return {
    status,
    isConnected,
    error,
    reconnectAttempt,
    agents,
    tasks,
    health,
    schedulerStats: schedulerStats || DEFAULT_SCHEDULER_STATS,
    deliberations,
    recentEvents,
    reconnect,
    disconnect,
    sendPing,
  };
}

export default useControlPlaneWebSocket;
