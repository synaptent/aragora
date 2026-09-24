'use client';

import { create } from 'zustand';
import { devtools, subscribeWithSelector } from 'zustand/middleware';

// ============================================================================
// Types
// ============================================================================

export type AgentStatus = 'starting' | 'available' | 'busy' | 'draining' | 'offline' | 'failed';
export type TaskStatus =
  'pending' | 'assigned' | 'running' | 'completed' | 'failed' | 'cancelled' | 'timeout';
export type TaskPriority = 'low' | 'normal' | 'high' | 'urgent';

export interface ControlPlaneAgent {
  agent_id: string;
  name?: string;
  provider: string;
  status: AgentStatus;
  model?: string;
  capabilities: string[];
  elo_rating?: number;
  tasks_completed?: number;
  tasks_failed?: number;
  avg_latency_ms?: number;
  last_heartbeat?: string;
  registered_at?: string;
  metadata?: Record<string, unknown>;
}

export interface ControlPlaneTask {
  id: string;
  name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  assigned_agent?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
}

export interface ControlPlaneHealth {
  status: 'healthy' | 'degraded' | 'unhealthy';
  agents: Record<
    string,
    {
      agent_id: string;
      status: 'healthy' | 'degraded' | 'unhealthy';
      last_heartbeat?: string;
      latency_ms?: number;
      error_rate?: number;
    }
  >;
  agents_available?: number;
  agents_total?: number;
  active_tasks?: number;
  uptime_seconds?: number;
  timestamp?: string;
}

export interface ControlPlaneStats {
  total_agents: number;
  available_agents: number;
  busy_agents: number;
  offline_agents: number;
  pending_tasks: number;
  running_tasks: number;
  completed_tasks_24h: number;
  failed_tasks_24h: number;
  avg_task_duration_ms?: number;
  queue_size: number;
  uptime_seconds?: number;
}

// ============================================================================
// Store State
// ============================================================================

interface ControlPlaneState {
  // Agent registry
  agents: ControlPlaneAgent[];
  agentsLoading: boolean;
  agentsError: string | null;

  // Task queue
  tasks: ControlPlaneTask[];
  tasksLoading: boolean;
  tasksError: string | null;
  taskFilters: { status?: ControlPlaneTask['status']; agentId?: string };

  // System health
  health: ControlPlaneHealth | null;
  healthLoading: boolean;

  // System stats
  stats: ControlPlaneStats | null;
  statsLoading: boolean;

  // Real-time updates
  lastUpdate: number | null;
  isConnected: boolean;

  // Selected items for detail view
  selectedAgentId: string | null;
  selectedTaskId: string | null;
}

interface ControlPlaneActions {
  // Agent actions
  setAgents: (agents: ControlPlaneAgent[]) => void;
  updateAgent: (agent: ControlPlaneAgent) => void;
  removeAgent: (agentId: string) => void;
  setAgentsLoading: (loading: boolean) => void;
  setAgentsError: (error: string | null) => void;

  // Task actions
  setTasks: (tasks: ControlPlaneTask[]) => void;
  updateTask: (task: ControlPlaneTask) => void;
  removeTask: (taskId: string) => void;
  setTasksLoading: (loading: boolean) => void;
  setTasksError: (error: string | null) => void;
  setTaskFilters: (filters: Partial<ControlPlaneState['taskFilters']>) => void;

  // Health actions
  setHealth: (health: ControlPlaneHealth | null) => void;
  setHealthLoading: (loading: boolean) => void;

  // Stats actions
  setStats: (stats: ControlPlaneStats | null) => void;
  setStatsLoading: (loading: boolean) => void;

  // Connection actions
  setIsConnected: (connected: boolean) => void;
  setLastUpdate: (timestamp: number) => void;

  // Selection actions
  setSelectedAgentId: (id: string | null) => void;
  setSelectedTaskId: (id: string | null) => void;

  // Reset
  resetAll: () => void;
}

type ControlPlaneStore = ControlPlaneState & ControlPlaneActions;

// ============================================================================
// Initial State
// ============================================================================

const initialState: ControlPlaneState = {
  agents: [],
  agentsLoading: false,
  agentsError: null,
  tasks: [],
  tasksLoading: false,
  tasksError: null,
  taskFilters: {},
  health: null,
  healthLoading: false,
  stats: null,
  statsLoading: false,
  lastUpdate: null,
  isConnected: false,
  selectedAgentId: null,
  selectedTaskId: null,
};

// ============================================================================
// Store Implementation
// ============================================================================

export const useControlPlaneStore = create<ControlPlaneStore>()(
  devtools(
    subscribeWithSelector((set) => ({
      ...initialState,

      // Agent actions
      setAgents: (agents) => set({ agents, agentsLoading: false, agentsError: null }),
      updateAgent: (agent) =>
        set((state) => {
          const idx = state.agents.findIndex((a) => a.agent_id === agent.agent_id);
          if (idx >= 0) {
            const agents = [...state.agents];
            agents[idx] = agent;
            return { agents };
          }
          return { agents: [...state.agents, agent] };
        }),
      removeAgent: (agentId) =>
        set((state) => ({ agents: state.agents.filter((a) => a.agent_id !== agentId) })),
      setAgentsLoading: (agentsLoading) => set({ agentsLoading }),
      setAgentsError: (agentsError) => set({ agentsError, agentsLoading: false }),

      // Task actions
      setTasks: (tasks) => set({ tasks, tasksLoading: false, tasksError: null }),
      updateTask: (task) =>
        set((state) => {
          const idx = state.tasks.findIndex((t) => t.id === task.id);
          if (idx >= 0) {
            const tasks = [...state.tasks];
            tasks[idx] = task;
            return { tasks };
          }
          return { tasks: [...state.tasks, task] };
        }),
      removeTask: (taskId) =>
        set((state) => ({ tasks: state.tasks.filter((t) => t.id !== taskId) })),
      setTasksLoading: (tasksLoading) => set({ tasksLoading }),
      setTasksError: (tasksError) => set({ tasksError, tasksLoading: false }),
      setTaskFilters: (filters) =>
        set((state) => ({ taskFilters: { ...state.taskFilters, ...filters } })),

      // Health actions
      setHealth: (health) => set({ health, healthLoading: false }),
      setHealthLoading: (healthLoading) => set({ healthLoading }),

      // Stats actions
      setStats: (stats) => set({ stats, statsLoading: false }),
      setStatsLoading: (statsLoading) => set({ statsLoading }),

      // Connection actions
      setIsConnected: (isConnected) => set({ isConnected }),
      setLastUpdate: (lastUpdate) => set({ lastUpdate }),

      // Selection actions
      setSelectedAgentId: (selectedAgentId) => set({ selectedAgentId }),
      setSelectedTaskId: (selectedTaskId) => set({ selectedTaskId }),

      // Reset
      resetAll: () => set(initialState),
    })),
    { name: 'control-plane-store' },
  ),
);

// ============================================================================
// Selectors
// ============================================================================

export const selectAgents = (state: ControlPlaneStore) => state.agents;
export const selectAgentsLoading = (state: ControlPlaneStore) => state.agentsLoading;
export const selectAgentsError = (state: ControlPlaneStore) => state.agentsError;

export const selectTasks = (state: ControlPlaneStore) => state.tasks;
export const selectTasksLoading = (state: ControlPlaneStore) => state.tasksLoading;
export const selectTasksError = (state: ControlPlaneStore) => state.tasksError;
export const selectTaskFilters = (state: ControlPlaneStore) => state.taskFilters;

export const selectHealth = (state: ControlPlaneStore) => state.health;
export const selectHealthLoading = (state: ControlPlaneStore) => state.healthLoading;

export const selectStats = (state: ControlPlaneStore) => state.stats;
export const selectStatsLoading = (state: ControlPlaneStore) => state.statsLoading;

export const selectIsConnected = (state: ControlPlaneStore) => state.isConnected;
export const selectLastUpdate = (state: ControlPlaneStore) => state.lastUpdate;

export const selectSelectedAgentId = (state: ControlPlaneStore) => state.selectedAgentId;
export const selectSelectedTaskId = (state: ControlPlaneStore) => state.selectedTaskId;

// Derived selectors
export const selectAgentById = (agentId: string) => (state: ControlPlaneStore) =>
  state.agents.find((a) => a.agent_id === agentId);

export const selectTaskById = (taskId: string) => (state: ControlPlaneStore) =>
  state.tasks.find((t) => t.id === taskId);

export const selectAgentsByStatus =
  (status: ControlPlaneAgent['status']) => (state: ControlPlaneStore) =>
    state.agents.filter((a) => a.status === status);

export const selectTasksByStatus =
  (status: ControlPlaneTask['status']) => (state: ControlPlaneStore) =>
    state.tasks.filter((t) => t.status === status);

export const selectFilteredTasks = (state: ControlPlaneStore) => {
  let filtered = state.tasks;
  if (state.taskFilters.status) {
    filtered = filtered.filter((t) => t.status === state.taskFilters.status);
  }
  if (state.taskFilters.agentId) {
    filtered = filtered.filter((t) => t.assigned_agent === state.taskFilters.agentId);
  }
  return filtered;
};

export const selectIsHealthy = (state: ControlPlaneStore) => state.health?.status === 'healthy';

export const selectAgentCount = (state: ControlPlaneStore) => ({
  total: state.agents.length,
  available: state.agents.filter((a) => a.status === 'available').length,
  busy: state.agents.filter((a) => a.status === 'busy').length,
  offline: state.agents.filter((a) => a.status === 'offline').length,
});

export const selectTaskCount = (state: ControlPlaneStore) => ({
  total: state.tasks.length,
  pending: state.tasks.filter((t) => t.status === 'pending').length,
  running: state.tasks.filter((t) => t.status === 'running').length,
  completed: state.tasks.filter((t) => t.status === 'completed').length,
  failed: state.tasks.filter((t) => t.status === 'failed').length,
});

export default useControlPlaneStore;
