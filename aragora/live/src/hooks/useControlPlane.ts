'use client';

/**
 * Control Plane hook for managing agents and tasks.
 *
 * Provides:
 * - Agent listing and status tracking
 * - Task management and filtering
 * - System health monitoring
 * - Real-time updates via WebSocket integration
 */

import { useCallback, useEffect, useRef } from 'react';
import { useAragoraClient } from './useAragoraClient';
import {
  useControlPlaneStore,
  selectAgents,
  selectAgentsLoading,
  selectAgentsError,
  selectTasks,
  selectTasksLoading,
  selectTasksError,
  selectHealth,
  selectHealthLoading,
  selectStats,
  selectStatsLoading,
  selectIsConnected,
  selectFilteredTasks,
  selectAgentCount,
  selectTaskCount,
  selectIsHealthy,
  type ControlPlaneAgent,
  type ControlPlaneTask,
} from '@/store/controlPlaneStore';
import { useControlPlaneWebSocket } from './useControlPlaneWebSocket';

export interface UseControlPlaneOptions {
  /** Whether to enable real-time WebSocket updates */
  enableRealtime?: boolean;
  /** Auto-refresh interval in ms (0 to disable) */
  refreshInterval?: number;
  /** Whether to load data on mount */
  loadOnMount?: boolean;
}

export interface UseControlPlaneReturn {
  // Data
  agents: ControlPlaneAgent[];
  tasks: ControlPlaneTask[];
  filteredTasks: ControlPlaneTask[];
  health: ReturnType<typeof selectHealth>;
  stats: ReturnType<typeof selectStats>;

  // Counts
  agentCount: ReturnType<typeof selectAgentCount>;
  taskCount: ReturnType<typeof selectTaskCount>;

  // Status
  isHealthy: boolean;
  isConnected: boolean;
  agentsLoading: boolean;
  tasksLoading: boolean;
  healthLoading: boolean;
  statsLoading: boolean;
  agentsError: string | null;
  tasksError: string | null;

  // Actions
  loadAgents: () => Promise<void>;
  loadTasks: () => Promise<void>;
  loadHealth: () => Promise<void>;
  loadStats: () => Promise<void>;
  loadAll: () => Promise<void>;

  createTask: (data: { name: string; agent_id?: string }) => Promise<ControlPlaneTask>;
  cancelTask: (taskId: string) => Promise<void>;

  setTaskFilters: (filters: { status?: ControlPlaneTask['status']; agentId?: string }) => void;

  selectAgent: (agentId: string | null) => void;
  selectTask: (taskId: string | null) => void;
}

/**
 * Hook for interacting with the Control Plane.
 *
 * @example
 * ```tsx
 * const {
 *   agents,
 *   tasks,
 *   isHealthy,
 *   loadAll,
 *   createTask,
 *   cancelTask,
 * } = useControlPlane({ enableRealtime: true });
 *
 * // Create a new task
 * const task = await createTask({ name: 'Document Analysis' });
 * ```
 */
export function useControlPlane({
  enableRealtime = true,
  refreshInterval = 0,
  loadOnMount = true,
}: UseControlPlaneOptions = {}): UseControlPlaneReturn {
  const client = useAragoraClient();
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  // Store selectors
  const agents = useControlPlaneStore(selectAgents);
  const agentsLoading = useControlPlaneStore(selectAgentsLoading);
  const agentsError = useControlPlaneStore(selectAgentsError);
  const tasks = useControlPlaneStore(selectTasks);
  const tasksLoading = useControlPlaneStore(selectTasksLoading);
  const tasksError = useControlPlaneStore(selectTasksError);
  const health = useControlPlaneStore(selectHealth);
  const healthLoading = useControlPlaneStore(selectHealthLoading);
  const stats = useControlPlaneStore(selectStats);
  const statsLoading = useControlPlaneStore(selectStatsLoading);
  const isConnected = useControlPlaneStore(selectIsConnected);
  const filteredTasks = useControlPlaneStore(selectFilteredTasks);
  const agentCount = useControlPlaneStore(selectAgentCount);
  const taskCount = useControlPlaneStore(selectTaskCount);
  const isHealthy = useControlPlaneStore(selectIsHealthy);

  // Store actions
  const setAgents = useControlPlaneStore((s) => s.setAgents);
  const setAgentsLoading = useControlPlaneStore((s) => s.setAgentsLoading);
  const setAgentsError = useControlPlaneStore((s) => s.setAgentsError);
  const updateAgent = useControlPlaneStore((s) => s.updateAgent);
  const setTasks = useControlPlaneStore((s) => s.setTasks);
  const setTasksLoading = useControlPlaneStore((s) => s.setTasksLoading);
  const setTasksError = useControlPlaneStore((s) => s.setTasksError);
  const updateTask = useControlPlaneStore((s) => s.updateTask);
  const setTaskFiltersAction = useControlPlaneStore((s) => s.setTaskFilters);
  const setHealth = useControlPlaneStore((s) => s.setHealth);
  const setHealthLoading = useControlPlaneStore((s) => s.setHealthLoading);
  const setStats = useControlPlaneStore((s) => s.setStats);
  const setStatsLoading = useControlPlaneStore((s) => s.setStatsLoading);
  const setIsConnected = useControlPlaneStore((s) => s.setIsConnected);
  const setLastUpdate = useControlPlaneStore((s) => s.setLastUpdate);
  const setSelectedAgentId = useControlPlaneStore((s) => s.setSelectedAgentId);
  const setSelectedTaskId = useControlPlaneStore((s) => s.setSelectedTaskId);

  // Real-time updates via WebSocket
  const {
    isConnected: wsConnected,
    agents: wsAgentsMap,
    tasks: wsTasksMap,
  } = useControlPlaneWebSocket({
    enabled: enableRealtime,
    onAgentRegistered: (agentId, data) => {
      // Add new agent to store
      updateAgent({
        agent_id: agentId,
        name: (data.name as string) || agentId,
        provider: (data.provider as string) || '',
        model: (data.model as string) || 'unknown',
        capabilities: (data.capabilities as string[]) || [],
        status: 'available',
      });
      setLastUpdate(Date.now());
    },
    onAgentStatusChanged: (agentId, _oldStatus, newStatus) => {
      // Map WebSocket agent format to store format
      const statusMap: Record<string, 'available' | 'busy' | 'draining' | 'offline'> = {
        idle: 'available',
        busy: 'busy',
        working: 'busy',
        rate_limited: 'draining',
        error: 'offline',
        offline: 'offline',
      };
      // Get current agent data from map
      const agent = wsAgentsMap.get(agentId);
      updateAgent({
        agent_id: agentId,
        name: agent?.name || agentId,
        provider: agent?.provider || '',
        model: agent?.model || 'unknown',
        capabilities: agent?.capabilities || [],
        status: statusMap[newStatus] || 'offline',
      });
      setLastUpdate(Date.now());
    },
    onTaskSubmitted: (taskId, data) => {
      // Add new task to store
      updateTask({
        id: taskId,
        name: (data.task_type as string) || taskId,
        status: 'pending',
        created_at: new Date().toISOString(),
      });
      setLastUpdate(Date.now());
    },
    onTaskClaimed: (taskId, agentId) => {
      const task = wsTasksMap.get(taskId);
      updateTask({
        id: taskId,
        name: task?.task_type || taskId,
        status: 'running',
        assigned_agent: agentId,
        created_at: task?.created_at || new Date().toISOString(),
        started_at: new Date().toISOString(),
      });
      setLastUpdate(Date.now());
    },
    onTaskCompleted: (taskId, agentId, _result) => {
      const task = wsTasksMap.get(taskId);
      updateTask({
        id: taskId,
        name: task?.task_type || taskId,
        status: 'completed',
        assigned_agent: agentId,
        created_at: task?.created_at || new Date().toISOString(),
        started_at: task?.started_at,
        completed_at: new Date().toISOString(),
      });
      setLastUpdate(Date.now());
    },
    onTaskFailed: (taskId, agentId, error) => {
      const task = wsTasksMap.get(taskId);
      updateTask({
        id: taskId,
        name: task?.task_type || taskId,
        status: 'failed',
        assigned_agent: agentId,
        created_at: task?.created_at || new Date().toISOString(),
        started_at: task?.started_at,
        completed_at: new Date().toISOString(),
        error: error,
      });
      setLastUpdate(Date.now());
    },
    onSchedulerStats: (stats) => {
      setStats({
        total_agents: stats.agents_registered,
        available_agents: stats.agents_idle,
        busy_agents: stats.agents_busy,
        offline_agents: 0,
        pending_tasks: stats.pending_tasks,
        running_tasks: stats.running_tasks,
        completed_tasks_24h: stats.completed_tasks,
        failed_tasks_24h: stats.failed_tasks,
        queue_size: stats.pending_tasks,
      });
    },
  });

  // Update connection status
  useEffect(() => {
    setIsConnected(wsConnected);
  }, [wsConnected, setIsConnected]);

  // Load agents from SDK
  const loadAgents = useCallback(async () => {
    if (!client) return;
    setAgentsLoading(true);
    try {
      const response = await client.controlPlane.listAgents();
      setAgents(response.agents);
    } catch (err) {
      setAgentsError(err instanceof Error ? err.message : 'Failed to load agents');
    }
  }, [client, setAgents, setAgentsLoading, setAgentsError]);

  // Load tasks from SDK
  const loadTasks = useCallback(async () => {
    if (!client) return;
    setTasksLoading(true);
    try {
      const response = await client.controlPlane.listTasks();
      setTasks(response.tasks);
    } catch (err) {
      setTasksError(err instanceof Error ? err.message : 'Failed to load tasks');
    }
  }, [client, setTasks, setTasksLoading, setTasksError]);

  // Load health from SDK
  const loadHealth = useCallback(async () => {
    if (!client) return;
    setHealthLoading(true);
    try {
      const response = await client.controlPlane.health();
      setHealth(response.health);
    } catch {
      setHealth(null);
    }
  }, [client, setHealth, setHealthLoading]);

  // Load stats - derived from health for now
  const loadStats = useCallback(async () => {
    if (!client) return;
    setStatsLoading(true);
    try {
      const response = await client.controlPlane.health();
      const health = response.health;
      const totalAgents = health.agents_total ?? Object.keys(health.agents).length;
      const availableAgents =
        health.agents_available ??
        Object.values(health.agents).filter((a) => a.status === 'healthy').length;
      // Map health to stats format
      setStats({
        total_agents: totalAgents,
        available_agents: availableAgents,
        busy_agents: totalAgents - availableAgents,
        offline_agents: 0,
        pending_tasks: 0,
        running_tasks: health.active_tasks ?? 0,
        completed_tasks_24h: 0,
        failed_tasks_24h: 0,
        queue_size: 0,
        uptime_seconds: health.uptime_seconds,
      });
    } catch {
      setStats(null);
    }
  }, [client, setStats, setStatsLoading]);

  // Load all data
  const loadAll = useCallback(async () => {
    await Promise.all([loadAgents(), loadTasks(), loadHealth(), loadStats()]);
  }, [loadAgents, loadTasks, loadHealth, loadStats]);

  // Create task
  const createTask = useCallback(
    async (data: { name: string; agent_id?: string }): Promise<ControlPlaneTask> => {
      if (!client) throw new Error('Client not available');
      const response = await client.controlPlane.createTask(data);
      updateTask(response.task);
      return response.task;
    },
    [client, updateTask],
  );

  // Cancel task
  const cancelTask = useCallback(
    async (taskId: string): Promise<void> => {
      if (!client) throw new Error('Client not available');
      await client.controlPlane.cancelTask(taskId);
      // Refresh tasks after cancel
      loadTasks();
    },
    [client, loadTasks],
  );

  // Set task filters
  const setTaskFilters = useCallback(
    (filters: { status?: ControlPlaneTask['status']; agentId?: string }) => {
      setTaskFiltersAction(filters);
    },
    [setTaskFiltersAction],
  );

  // Selection actions
  const selectAgent = useCallback(
    (agentId: string | null) => {
      setSelectedAgentId(agentId);
    },
    [setSelectedAgentId],
  );

  const selectTask = useCallback(
    (taskId: string | null) => {
      setSelectedTaskId(taskId);
    },
    [setSelectedTaskId],
  );

  // Load on mount
  useEffect(() => {
    if (loadOnMount && client) {
      loadAll();
    }
  }, [loadOnMount, client, loadAll]);

  // Auto-refresh
  useEffect(() => {
    if (refreshInterval > 0) {
      intervalRef.current = setInterval(() => {
        loadAll();
      }, refreshInterval);
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [refreshInterval, loadAll]);

  return {
    // Data
    agents,
    tasks,
    filteredTasks,
    health,
    stats,

    // Counts
    agentCount,
    taskCount,

    // Status
    isHealthy,
    isConnected,
    agentsLoading,
    tasksLoading,
    healthLoading,
    statsLoading,
    agentsError,
    tasksError,

    // Actions
    loadAgents,
    loadTasks,
    loadHealth,
    loadStats,
    loadAll,
    createTask,
    cancelTask,
    setTaskFilters,
    selectAgent,
    selectTask,
  };
}

export default useControlPlane;
