/**
 * Tests for useControlPlane hook
 */

import { renderHook } from '@testing-library/react';
import { useControlPlane } from '@/hooks/useControlPlane';

// Mock the store selectors
const mockAgents = [
  { id: 'agent-1', name: 'claude', status: 'READY', capabilities: ['debate'] },
  { id: 'agent-2', name: 'gpt4', status: 'BUSY', capabilities: ['debate', 'analysis'] },
];

const mockTasks = [
  { id: 'task-1', name: 'Test debate', status: 'running', agent_id: 'agent-1' },
  { id: 'task-2', name: 'Analysis', status: 'pending', agent_id: null },
];

const mockSetTaskFilters = jest.fn();
const mockSetSearchQuery = jest.fn();
const mockSetAgents = jest.fn();
const mockSetTasks = jest.fn();
const mockSetHealth = jest.fn();
const mockSetStats = jest.fn();
const mockSetAgentsLoading = jest.fn();
const mockSetTasksLoading = jest.fn();
const mockSetHealthLoading = jest.fn();
const mockSetStatsLoading = jest.fn();
const mockSetAgentsError = jest.fn();
const mockSetTasksError = jest.fn();
const mockUpdateAgent = jest.fn();
const mockUpdateTask = jest.fn();
const mockSetIsConnected = jest.fn();
const mockSetLastUpdate = jest.fn();
const mockSetSelectedAgentId = jest.fn();
const mockSetSelectedTaskId = jest.fn();

jest.mock('@/store/controlPlaneStore', () => ({
  useControlPlaneStore: jest.fn((selector) => {
    const state = {
      agents: mockAgents,
      agentsLoading: false,
      agentsError: null,
      tasks: mockTasks,
      tasksLoading: false,
      tasksError: null,
      health: { status: 'healthy', uptime: 3600 },
      healthLoading: false,
      stats: { total_agents: 2, total_tasks: 2 },
      statsLoading: false,
      isConnected: true,
      taskFilters: {},
      searchQuery: '',
      setAgents: mockSetAgents,
      setTasks: mockSetTasks,
      setHealth: mockSetHealth,
      setStats: mockSetStats,
      setAgentsLoading: mockSetAgentsLoading,
      setTasksLoading: mockSetTasksLoading,
      setHealthLoading: mockSetHealthLoading,
      setStatsLoading: mockSetStatsLoading,
      setAgentsError: mockSetAgentsError,
      setTasksError: mockSetTasksError,
      updateAgent: mockUpdateAgent,
      updateTask: mockUpdateTask,
      setIsConnected: mockSetIsConnected,
      setLastUpdate: mockSetLastUpdate,
      setSelectedAgentId: mockSetSelectedAgentId,
      setSelectedTaskId: mockSetSelectedTaskId,
      setTaskFilters: mockSetTaskFilters,
      setSearchQuery: mockSetSearchQuery,
      setIsConnected: jest.fn(),
      setConnectionStatus: jest.fn(),
    };
    return selector(state);
  }),
  selectAgents: (s: Record<string, unknown>) => s.agents,
  selectAgentsLoading: (s: Record<string, unknown>) => s.agentsLoading,
  selectAgentsError: (s: Record<string, unknown>) => s.agentsError,
  selectTasks: (s: Record<string, unknown>) => s.tasks,
  selectTasksLoading: (s: Record<string, unknown>) => s.tasksLoading,
  selectTasksError: (s: Record<string, unknown>) => s.tasksError,
  selectHealth: (s: Record<string, unknown>) => s.health,
  selectHealthLoading: (s: Record<string, unknown>) => s.healthLoading,
  selectStats: (s: Record<string, unknown>) => s.stats,
  selectStatsLoading: (s: Record<string, unknown>) => s.statsLoading,
  selectIsConnected: (s: Record<string, unknown>) => s.isConnected,
  selectFilteredTasks: (s: Record<string, unknown>) => s.tasks,
  selectAgentCount: (s: Record<string, unknown>) => ({
    total: (s.agents as unknown[]).length,
    ready: 1,
    busy: 1,
    offline: 0,
  }),
  selectTaskCount: (s: Record<string, unknown>) => ({
    total: (s.tasks as unknown[]).length,
    running: 1,
    pending: 1,
    completed: 0,
  }),
  selectIsHealthy: (s: Record<string, unknown>) => s.health !== null,
}));

// Mock useAragoraClient
const mockGet = jest.fn();
const mockPost = jest.fn();
jest.mock('@/hooks/useAragoraClient', () => ({
  useAragoraClient: () => ({ get: mockGet, post: mockPost }),
}));

// Mock useControlPlaneWebSocket
jest.mock('@/hooks/useControlPlaneWebSocket', () => ({
  useControlPlaneWebSocket: jest.fn(() => ({
    isConnected: true,
    agents: new Map(),
    tasks: new Map(),
    lastMessage: null,
  })),
}));

describe('useControlPlane', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGet.mockResolvedValue({ data: [] });
    mockPost.mockResolvedValue({ data: {} });
  });

  it('returns agent and task data from store', () => {
    const { result } = renderHook(() => useControlPlane());
    expect(result.current.agents).toEqual(mockAgents);
    expect(result.current.tasks).toEqual(mockTasks);
  });

  it('returns loading states', () => {
    const { result } = renderHook(() => useControlPlane());
    expect(result.current.agentsLoading).toBe(false);
    expect(result.current.tasksLoading).toBe(false);
    expect(result.current.healthLoading).toBe(false);
    expect(result.current.statsLoading).toBe(false);
  });

  it('returns connection status', () => {
    const { result } = renderHook(() => useControlPlane());
    expect(result.current.isConnected).toBe(true);
  });

  it('returns health status', () => {
    const { result } = renderHook(() => useControlPlane());
    expect(result.current.health).toEqual({ status: 'healthy', uptime: 3600 });
    expect(result.current.isHealthy).toBe(true);
  });

  it('returns agent and task counts', () => {
    const { result } = renderHook(() => useControlPlane());
    expect(result.current.agentCount.total).toBe(2);
    expect(result.current.taskCount.total).toBe(2);
  });

  it('returns no errors initially', () => {
    const { result } = renderHook(() => useControlPlane());
    expect(result.current.agentsError).toBeNull();
    expect(result.current.tasksError).toBeNull();
  });

  it('provides action functions', () => {
    const { result } = renderHook(() => useControlPlane());
    expect(typeof result.current.loadAgents).toBe('function');
    expect(typeof result.current.loadTasks).toBe('function');
    expect(typeof result.current.loadHealth).toBe('function');
    expect(typeof result.current.loadStats).toBe('function');
    expect(typeof result.current.loadAll).toBe('function');
    expect(typeof result.current.createTask).toBe('function');
    expect(typeof result.current.cancelTask).toBe('function');
    expect(typeof result.current.setTaskFilters).toBe('function');
  });

  it('provides stats from store', () => {
    const { result } = renderHook(() => useControlPlane());
    expect(result.current.stats).toEqual({ total_agents: 2, total_tasks: 2 });
  });
});
