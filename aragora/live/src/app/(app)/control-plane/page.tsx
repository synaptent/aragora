'use client';

import { useState, useEffect, useCallback } from 'react';
import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useControlPlaneWebSocket, type TaskState } from '@/hooks/useControlPlaneWebSocket';
import { logger } from '@/utils/logger';

// Lazy load heavy visualization component
const AgentWorkflowVisualization = dynamic(
  () =>
    import('@/components/AgentWorkflowVisualization').then((m) => ({
      default: m.AgentWorkflowVisualization,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="h-[350px] flex items-center justify-center text-text-muted">
        Loading visualization...
      </div>
    ),
  },
);
import {
  type Agent,
  type ProcessingJob,
  type SystemMetrics,
  type TabId,
  getStatusColor,
  formatTokens,
  TABS,
} from './types';

// Control Plane Components
import {
  AgentCatalog,
  WorkflowBuilder,
  KnowledgeExplorer,
  ExecutionMonitor,
  PolicyDashboard,
  WorkspaceManager,
  ConnectorDashboard,
  FleetStatusWidget,
  ActivityFeed,
  DeliberationTracker,
  SystemHealthDashboard,
  type FleetAgent,
  type ActivityEvent,
  type Deliberation,
} from '@/components/control-plane';

import { VerticalSelector } from '@/components/VerticalSelector';

export default function ControlPlanePage() {
  const { config: backendConfig } = useBackend();
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [agents, setAgents] = useState<Agent[]>([]);
  const [jobs, setJobs] = useState<ProcessingJob[]>([]);
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [autoRefresh] = useState(true);
  const [usingMockData, setUsingMockData] = useState(false);
  const [useWebSocket] = useState(true);
  const [selectedVertical, setSelectedVertical] = useState<string | null>(null);
  const [deliberationInput, setDeliberationInput] = useState('');
  const [deliberationDecisionType, setDeliberationDecisionType] = useState('debate');
  const [deliberationAsync, setDeliberationAsync] = useState(false);
  const [deliberationLoading, setDeliberationLoading] = useState(false);
  const [deliberationResult, setDeliberationResult] = useState<Record<string, unknown> | null>(
    null,
  );
  const [deliberationStatus, setDeliberationStatus] = useState<Record<string, unknown> | null>(
    null,
  );
  const [deliberationError, setDeliberationError] = useState<string | null>(null);
  const [verticalsData, setVerticalsData] = useState<
    Array<{
      vertical_id: string;
      display_name: string;
      description: string;
      expertise_areas?: string[];
      compliance_frameworks?: string[];
      default_model?: string;
    }>
  >([]);

  // WebSocket connection for real-time updates
  const {
    isConnected: wsConnected,
    agents: wsAgentsMap,
    tasks: wsTasksMap,
    schedulerStats,
    recentEvents,
  } = useControlPlaneWebSocket({
    enabled: useWebSocket,
    autoReconnect: true,
    onTaskCompleted: (_taskId, _agentId) => {
      // Could show a toast notification here
    },
  });

  // Convert Map to array and map to display format
  const wsAgentsArray = Array.from(wsAgentsMap.values());
  const wsTasksArray = Array.from(wsTasksMap.values());

  // Use WebSocket data when connected, otherwise use REST data
  const displayAgents =
    wsConnected && wsAgentsArray.length > 0
      ? wsAgentsArray.map((a) => ({
          id: a.id,
          name: a.id, // Use ID as name since new backend doesn't have separate name
          model: a.model,
          status: a.status === 'busy' ? 'working' : (a.status as Agent['status']),
          current_task: a.current_task_id,
          requests_today: 0, // Not tracked in new schema
          tokens_used: 0, // Not tracked in new schema
          last_active: a.last_heartbeat,
        }))
      : agents;

  const displayJobs =
    wsConnected && wsTasksArray.length > 0
      ? wsTasksArray.map((t) => ({
          id: t.id,
          type: t.task_type as ProcessingJob['type'],
          name: t.task_type,
          status: t.status === 'claimed' ? 'running' : (t.status as ProcessingJob['status']),
          progress: t.status === 'completed' ? 100 : t.status === 'running' ? 50 : 0,
          started_at: t.started_at,
          document_count: undefined,
          agents_assigned: t.assigned_agent_id ? [t.assigned_agent_id] : [],
        }))
      : jobs;

  const displayMetrics =
    wsConnected && schedulerStats
      ? {
          active_jobs: schedulerStats.running_tasks,
          queued_jobs: schedulerStats.pending_tasks,
          agents_available: schedulerStats.agents_idle,
          agents_busy: schedulerStats.agents_busy,
          documents_processed_today: 0, // Not tracked in new schema
          audits_completed_today: schedulerStats.completed_tasks,
          tokens_used_today: 0, // Not tracked in new schema
        }
      : metrics;

  // Map recent events to findings for backwards compatibility (if any task failed events)
  const recentFindings = recentEvents
    .filter((e) => e.type === 'task_failed')
    .slice(0, 50)
    .map((e) => ({
      id: e.data.task_id as string,
      session_id: '',
      document_id: '',
      severity: 'medium' as const,
      category: 'task_failure',
      title: `Task ${e.data.task_id} failed: ${e.data.error || 'Unknown error'}`,
      found_by: (e.data.agent_id as string) || 'unknown',
      timestamp: new Date(e.timestamp * 1000).toISOString(),
    }));

  // Convert agents to FleetAgent format for FleetStatusWidget
  const fleetAgents: FleetAgent[] = displayAgents.map((a) => ({
    id: a.id,
    name: a.name,
    model: a.model,
    status:
      a.status === 'working'
        ? 'busy'
        : a.status === 'idle'
          ? 'idle'
          : a.status === 'error'
            ? 'error'
            : 'offline',
    current_task_id: a.current_task,
    last_heartbeat: a.last_active,
  }));

  // Convert WebSocket events to ActivityEvent format
  const activityEvents: ActivityEvent[] = recentEvents
    .slice(0, 50)
    .map((e) => ({
      id: `${e.type}-${e.timestamp}`,
      type:
        e.type === 'agent_registered'
          ? 'agent_registered'
          : e.type === 'agent_unregistered'
            ? 'agent_offline'
            : e.type === 'task_completed'
              ? 'task_completed'
              : e.type === 'task_failed'
                ? 'task_failed'
                : e.type === 'task_submitted'
                  ? 'deliberation_started'
                  : 'task_completed',
      timestamp: new Date(e.timestamp * 1000).toISOString(),
      title:
        e.type === 'agent_registered'
          ? `Agent ${e.data.agent_id} registered`
          : e.type === 'agent_unregistered'
            ? `Agent ${e.data.agent_id} went offline`
            : e.type === 'task_completed'
              ? `Task completed by ${e.data.agent_id}`
              : e.type === 'task_failed'
                ? `Task failed: ${e.data.error || 'Unknown error'}`
                : e.type === 'task_submitted'
                  ? `New task submitted: ${e.data.task_type}`
                  : `Event: ${e.type}`,
      severity:
        e.type === 'task_failed' ? 'error' : e.type === 'agent_unregistered' ? 'warning' : 'info',
      actor: e.data.agent_id
        ? { type: 'agent' as const, id: e.data.agent_id as string, name: e.data.agent_id as string }
        : undefined,
    }));

  // Mock debate sessions data (would come from API in production)
  const [deliberations, setDeliberations] = useState<Deliberation[]>([]);

  // Fetch debate sessions
  useEffect(() => {
    const fetchDeliberations = async () => {
      try {
        const res = await fetch(`${backendConfig.api}/api/v1/deliberations`);
        if (res.ok) {
          const data = await res.json();
          const mapped = (data.deliberations || []).map((d: Record<string, unknown>) => {
            const agentsArray = Array.isArray(d.agents) ? d.agents : [];
            return {
              id: d.id || d.request_id,
              question: d.question || d.content || 'Unknown question',
              status:
                d.status === 'completed'
                  ? d.consensus_reached
                    ? 'consensus_reached'
                    : 'no_consensus'
                  : d.status === 'failed'
                    ? 'failed'
                    : d.status === 'in_progress'
                      ? 'in_progress'
                      : 'pending',
              started_at: d.started_at || d.created_at,
              completed_at: d.completed_at,
              current_round: d.current_round || 0,
              max_rounds: d.max_rounds || 5,
              agents: agentsArray.map((a: string | Record<string, unknown>) =>
                typeof a === 'string'
                  ? { id: a, name: a }
                  : {
                      id: (a as Record<string, unknown>).id,
                      name:
                        (a as Record<string, unknown>).name || (a as Record<string, unknown>).id,
                    },
              ),
              consensus_confidence: d.confidence,
              final_answer: d.final_answer || d.answer,
            };
          });
          setDeliberations(mapped);
        }
      } catch {
        // Deliberations endpoint may not be available
      }
    };
    fetchDeliberations();
    const interval = setInterval(fetchDeliberations, 10000);
    return () => clearInterval(interval);
  }, [backendConfig.api]);

  const submitDeliberation = useCallback(async () => {
    if (!deliberationInput.trim()) return;
    setDeliberationLoading(true);
    setDeliberationError(null);
    setDeliberationStatus(null);
    setDeliberationResult(null);
    try {
      const response = await fetch(`${backendConfig.api}/api/control-plane/deliberations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content: deliberationInput.trim(),
          decision_type: deliberationDecisionType,
          async: deliberationAsync,
          priority: 'high',
          response_channels: [{ platform: 'http_api' }],
          required_capabilities: ['deliberation'],
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.error || 'Debate request failed');
      }
      setDeliberationResult(data);
    } catch (err) {
      setDeliberationError(err instanceof Error ? err.message : 'Debate request failed');
    } finally {
      setDeliberationLoading(false);
    }
  }, [backendConfig.api, deliberationAsync, deliberationDecisionType, deliberationInput]);

  const checkDeliberationStatus = useCallback(async () => {
    const requestId = deliberationResult?.request_id as string | undefined;
    if (!requestId) return;
    setDeliberationLoading(true);
    setDeliberationError(null);
    try {
      const response = await fetch(
        `${backendConfig.api}/api/control-plane/deliberations/${requestId}/status`,
      );
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.error || 'Status check failed');
      }
      setDeliberationStatus(data);
    } catch (err) {
      setDeliberationError(err instanceof Error ? err.message : 'Status check failed');
    } finally {
      setDeliberationLoading(false);
    }
  }, [backendConfig.api, deliberationResult]);

  // Fetch agents from control plane API
  const fetchAgents = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/control-plane/agents`);
      if (!response.ok) throw new Error('Failed to fetch agents');
      const data = await response.json();
      // Map control plane agent format to UI format
      const mappedAgents = (data.agents || []).map((agent: Record<string, unknown>) => ({
        id: agent.id || agent.agent_id,
        name: agent.name || agent.id || agent.agent_id,
        model: agent.model || 'unknown',
        status:
          agent.status === 'ready' ? 'idle' : agent.status === 'busy' ? 'working' : agent.status,
        current_task: agent.current_task,
        requests_today: agent.requests_today || 0,
        tokens_used: agent.tokens_used || 0,
        last_active: agent.last_active || agent.last_heartbeat,
      }));
      setAgents(mappedAgents);
      return true; // Success
    } catch {
      // Demo mode: use mock data if endpoint not available
      setAgents([
        {
          id: 'claude',
          name: 'Claude',
          model: 'claude-3.5-sonnet',
          status: 'idle',
          requests_today: 45,
          tokens_used: 125000,
        },
        {
          id: 'gemini',
          name: 'Gemini',
          model: 'gemini-3-pro',
          status: 'working',
          current_task: 'Document audit scan',
          requests_today: 32,
          tokens_used: 890000,
        },
        {
          id: 'gpt4',
          name: 'GPT-4',
          model: 'gpt-4-turbo',
          status: 'idle',
          requests_today: 28,
          tokens_used: 78000,
        },
        {
          id: 'codex',
          name: 'Codex',
          model: 'claude-3.5-sonnet',
          status: 'idle',
          requests_today: 15,
          tokens_used: 45000,
        },
      ]);
      return false; // Used mock (demo mode)
    }
  }, [backendConfig.api]);

  // Fetch jobs from queue endpoint
  const fetchJobs = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/control-plane/queue`);
      if (!response.ok) throw new Error('Failed to fetch jobs');
      const data = await response.json();
      // Map backend job format to UI format
      const mappedJobs = (data.jobs || []).map((job: Record<string, unknown>) => ({
        id: job.id,
        type: job.type || 'task',
        name: job.name || `${job.type} task`,
        status: job.status === 'pending' ? 'queued' : job.status,
        progress: job.progress || 0,
        started_at: job.started_at,
        document_count: job.document_count || 0,
        agents_assigned: job.agents_assigned || [],
      }));
      setJobs(mappedJobs);
      return true; // Success
    } catch {
      // Demo mode: use mock data if endpoint not available
      setJobs([
        {
          id: 'job1',
          type: 'audit',
          name: 'Security Audit - Q1 Contracts',
          status: 'running',
          progress: 0.45,
          started_at: new Date().toISOString(),
          document_count: 12,
          agents_assigned: ['gemini', 'claude'],
        },
        {
          id: 'job2',
          type: 'document_processing',
          name: 'Batch Import - Legal Docs',
          status: 'queued',
          progress: 0,
          document_count: 48,
          agents_assigned: [],
        },
        {
          id: 'job3',
          type: 'audit',
          name: 'Compliance Check - HR Policies',
          status: 'completed',
          progress: 1,
          document_count: 5,
          agents_assigned: ['gemini'],
        },
      ]);
      return false; // Used mock (demo mode)
    }
  }, [backendConfig.api]);

  // Fetch metrics from control plane API
  const fetchMetrics = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/control-plane/metrics`);
      if (!response.ok) throw new Error('Failed to fetch metrics');
      const data = await response.json();
      setMetrics(data);
      return true; // Success
    } catch {
      // Demo mode: use mock data if endpoint not available
      setMetrics({
        active_jobs: 1,
        queued_jobs: 2,
        agents_available: 3,
        agents_busy: 1,
        documents_processed_today: 67,
        audits_completed_today: 4,
        tokens_used_today: 1138000,
      });
      return false; // Used mock (demo mode)
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api]);

  // Track mock data usage
  const fetchAllData = useCallback(async () => {
    const [agentsOk, jobsOk, metricsOk] = await Promise.all([
      fetchAgents(),
      fetchJobs(),
      fetchMetrics(),
    ]);
    setUsingMockData(!agentsOk || !jobsOk || !metricsOk);
  }, [fetchAgents, fetchJobs, fetchMetrics]);

  useEffect(() => {
    fetchAllData();
  }, [fetchAllData]);

  // Fetch verticals data
  useEffect(() => {
    const fetchVerticals = async () => {
      try {
        const res = await fetch(`${backendConfig.api}/api/verticals`);
        if (res.ok) {
          const data = await res.json();
          setVerticalsData(data.verticals || []);
        }
      } catch {
        // Verticals endpoint may not be available
      }
    };
    fetchVerticals();
  }, [backendConfig.api]);

  // Auto-refresh (fallback to polling when WebSocket is not connected)
  useEffect(() => {
    // Skip polling if WebSocket is connected and providing data
    if (wsConnected && (wsAgentsArray.length > 0 || wsTasksArray.length > 0)) return;
    if (!autoRefresh) return;

    const interval = setInterval(() => {
      fetchAllData();
    }, 5000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchAllData, wsConnected, wsAgentsArray.length, wsTasksArray.length]);

  const pauseJob = async (jobId: string) => {
    try {
      // Tasks can be cancelled, but not paused in current API
      // For now, cancelling is the closest action
      await fetch(`${backendConfig.api}/api/control-plane/tasks/${jobId}/cancel`, {
        method: 'POST',
      });
      fetchJobs();
    } catch {
      // Handle error - demo mode will continue with mock data
    }
  };

  const resumeJob = async (_jobId: string) => {
    try {
      // To "resume" we would resubmit the task - for now just refresh
      // A true pause/resume would need additional API support
      fetchJobs();
    } catch {
      // Handle error
    }
  };

  const cancelJob = async (jobId: string) => {
    try {
      await fetch(`${backendConfig.api}/api/control-plane/tasks/${jobId}/cancel`, {
        method: 'POST',
      });
      fetchJobs();
    } catch {
      // Handle error - demo mode will continue with mock data
    }
  };

  // Build tabs with dynamic counts
  const tabs = TABS.map((tab) => ({
    ...tab,
    count:
      tab.id === 'agents'
        ? displayAgents.length
        : tab.id === 'queue'
          ? displayJobs.filter((j) => j.status === 'running' || j.status === 'queued').length
          : undefined,
  }));

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Demo Mode Indicator */}
        {usingMockData && (
          <div className="bg-yellow-900/20 border-b border-yellow-600/30 py-2">
            <div className="container mx-auto px-4 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-yellow-400" />
              <span className="font-theme-data text-xs text-yellow-400">DEMO MODE</span>
            </div>
          </div>
        )}

        {/* Sub Navigation */}
        <div className="border-b border-[var(--accent)]/20 bg-surface/40">
          <div className="container mx-auto px-4">
            <div className="flex gap-4 overflow-x-auto">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`px-4 py-2 font-theme-data text-sm transition-colors flex items-center gap-2 ${
                    activeTab === tab.id
                      ? 'text-[var(--accent)] border-b-2 border-[var(--accent)]'
                      : 'text-text-muted hover:text-text'
                  }`}
                >
                  {tab.label}
                  {tab.count !== undefined && (
                    <span className="px-1.5 py-0.5 bg-surface rounded text-xs">{tab.count}</span>
                  )}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          <PanelErrorBoundary panelName="ControlPlane">
            {/* Page Header */}
            <div className="mb-6">
              <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">Dashboard</h1>
              <p className="text-text-muted font-theme-data text-sm">
                Monitor and orchestrate multi-agent document processing and auditing.
              </p>
            </div>

            {loading ? (
              <div className="card p-8 text-center">
                <div className="animate-pulse font-theme-data text-text-muted">
                  Loading dashboard...
                </div>
              </div>
            ) : (
              <>
                {/* Overview Tab */}
                {activeTab === 'overview' && displayMetrics && (
                  <div className="space-y-6">
                    {/* Top Row: Fleet Status + Activity Feed */}
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                      {/* Fleet Status Widget */}
                      <div className="lg:col-span-1">
                        <FleetStatusWidget
                          agents={fleetAgents}
                          runningTasks={displayMetrics.active_jobs}
                          queuedTasks={displayMetrics.queued_jobs}
                          onViewAgents={() => setActiveTab('agents')}
                        />
                      </div>

                      {/* Activity Feed */}
                      <div className="lg:col-span-2">
                        <ActivityFeed
                          events={activityEvents}
                          maxVisible={8}
                          compact={true}
                          showFilters={false}
                          title="Recent Activity"
                        />
                      </div>
                    </div>

                    {/* Debate Tracker */}
                    {deliberations.length > 0 && (
                      <DeliberationTracker
                        deliberations={deliberations}
                        maxVisible={5}
                        onDeliberationClick={(d) => {
                          // Could open a modal or navigate to decisionmaking detail
                          logger.debug('Selected decisionmaking session:', d.id);
                        }}
                      />
                    )}

                    {/* Metrics Grid */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      <div className="card p-4">
                        <div className="text-xs font-theme-data text-text-muted mb-1">
                          ACTIVE JOBS
                        </div>
                        <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                          {displayMetrics.active_jobs}
                        </div>
                      </div>
                      <div className="card p-4">
                        <div className="text-xs font-theme-data text-text-muted mb-1">QUEUED</div>
                        <div className="text-2xl font-theme-data text-[var(--acid-yellow)]">
                          {displayMetrics.queued_jobs}
                        </div>
                      </div>
                      <div className="card p-4">
                        <div className="text-xs font-theme-data text-text-muted mb-1">
                          AGENTS AVAILABLE
                        </div>
                        <div className="text-2xl font-theme-data text-success">
                          {displayMetrics.agents_available}/
                          {displayMetrics.agents_available + displayMetrics.agents_busy}
                        </div>
                      </div>
                      <div className="card p-4">
                        <div className="text-xs font-theme-data text-text-muted mb-1">
                          TOKENS TODAY
                        </div>
                        <div className="text-2xl font-theme-data">
                          {formatTokens(displayMetrics.tokens_used_today)}
                        </div>
                      </div>
                    </div>

                    {/* Agent Workflow Visualization */}
                    <div className="card p-4">
                      <AgentWorkflowVisualization
                        agents={displayAgents.map((a) => ({
                          ...a,
                          requests_today: a.requests_today,
                          tokens_used: a.tokens_used,
                          capabilities: [],
                          provider: 'unknown',
                        }))}
                        jobs={displayJobs.map((j) => ({
                          id: j.id,
                          task_type: j.type,
                          status: (j.status === 'queued'
                            ? 'pending'
                            : j.status === 'paused'
                              ? 'pending'
                              : j.status) as TaskState['status'],
                          priority: 'normal' as const,
                          required_capabilities: [],
                          agents_assigned: j.agents_assigned,
                          progress: j.progress,
                          started_at: j.started_at,
                          name: j.name,
                          type: j.type,
                          document_count: j.document_count,
                        }))}
                        width={850}
                        height={350}
                        onAgentClick={(_agent) => {
                          // Could navigate to agent detail or show modal
                        }}
                      />
                    </div>

                    {/* Active Jobs */}
                    <div className="card">
                      <div className="p-4 border-b border-border">
                        <h2 className="font-theme-data text-sm text-[var(--accent)]">
                          Active Jobs
                        </h2>
                      </div>
                      <div className="p-4 space-y-3">
                        {displayJobs.filter((j) => j.status === 'running').length === 0 ? (
                          <div className="text-center text-text-muted font-theme-data text-sm py-4">
                            No active jobs
                          </div>
                        ) : (
                          displayJobs
                            .filter((j) => j.status === 'running')
                            .map((job) => (
                              <div
                                key={job.id}
                                className="bg-surface p-3 rounded border border-border"
                              >
                                <div className="flex items-center justify-between mb-2">
                                  <span className="font-theme-data text-sm">{job.name}</span>
                                  <span
                                    className={`text-xs font-theme-data uppercase ${getStatusColor(job.status)}`}
                                  >
                                    {job.status}
                                  </span>
                                </div>
                                <div className="h-1.5 bg-bg rounded overflow-hidden mb-2">
                                  <div
                                    className="h-full bg-[var(--acid-cyan)] transition-all"
                                    style={{ width: `${job.progress * 100}%` }}
                                  />
                                </div>
                                <div className="flex items-center justify-between text-xs font-theme-data text-text-muted">
                                  <span>
                                    {Math.round(job.progress * 100)}% - {job.document_count}{' '}
                                    documents
                                  </span>
                                  <span>Agents: {job.agents_assigned.join(', ')}</span>
                                </div>
                              </div>
                            ))
                        )}
                      </div>
                    </div>

                    {/* Agent Status */}
                    <div className="card">
                      <div className="p-4 border-b border-border">
                        <h2 className="font-theme-data text-sm text-[var(--accent)]">
                          Agent Status
                        </h2>
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 p-4">
                        {displayAgents.map((agent) => (
                          <div
                            key={agent.id}
                            className="bg-surface p-3 rounded border border-border"
                          >
                            <div className="flex items-center gap-2 mb-2">
                              <span
                                className={`w-2 h-2 rounded-full ${
                                  agent.status === 'working'
                                    ? 'bg-[var(--acid-cyan)] animate-pulse'
                                    : agent.status === 'idle'
                                      ? 'bg-success'
                                      : 'bg-[var(--crimson)]'
                                }`}
                              />
                              <span className="font-theme-data text-sm">{agent.name}</span>
                            </div>
                            <div className="text-xs font-theme-data text-text-muted">
                              {agent.current_task || agent.model}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Decision Console */}
                    <div className="card">
                      <div className="p-4 border-b border-border">
                        <h2 className="font-theme-data text-sm text-[var(--accent)]">
                          Decision Console
                        </h2>
                        <p className="text-text-muted text-xs font-theme-data mt-1">
                          Submit decisions for AI debate and capture decision receipts.
                        </p>
                      </div>
                      <div className="p-4 space-y-4">
                        <textarea
                          className="w-full min-h-[120px] bg-surface border border-border rounded p-3 text-sm font-theme-data text-text"
                          placeholder="Describe the decision to debate..."
                          value={deliberationInput}
                          onChange={(event) => setDeliberationInput(event.target.value)}
                        />
                        <div className="flex flex-wrap items-center gap-4">
                          <label className="text-xs font-theme-data text-text-muted">
                            Decision Type
                            <select
                              className="ml-2 bg-surface border border-border rounded px-2 py-1 text-xs text-text"
                              value={deliberationDecisionType}
                              onChange={(event) => setDeliberationDecisionType(event.target.value)}
                            >
                              <option value="auto">AUTO</option>
                              <option value="debate">DEBATE</option>
                              <option value="gauntlet">GAUNTLET</option>
                              <option value="workflow">WORKFLOW</option>
                              <option value="quick">QUICK</option>
                            </select>
                          </label>
                          <label className="flex items-center gap-2 text-xs font-theme-data text-text-muted">
                            <input
                              type="checkbox"
                              className="accent-acid-green"
                              checked={deliberationAsync}
                              onChange={(event) => setDeliberationAsync(event.target.checked)}
                            />
                            ASYNC
                          </label>
                          <button
                            className="ml-auto px-3 py-1.5 rounded border border-[var(--accent)] text-[var(--accent)] text-xs font-theme-data hover:bg-[var(--accent)]/10 disabled:opacity-50"
                            onClick={submitDeliberation}
                            disabled={deliberationLoading || !deliberationInput.trim()}
                          >
                            {deliberationLoading ? 'SUBMITTING...' : 'START DEBATE'}
                          </button>
                        </div>
                        {deliberationError && (
                          <div className="text-[var(--crimson)] text-xs font-theme-data">
                            {deliberationError}
                          </div>
                        )}
                        {deliberationResult && (
                          <div className="bg-surface border border-border rounded p-3 text-xs font-theme-data text-text-muted space-y-2">
                            <div className="text-text">
                              Status: {String(deliberationResult.status || 'unknown')}
                            </div>
                            {Boolean(deliberationResult.request_id) && (
                              <div>Request ID: {String(deliberationResult.request_id)}</div>
                            )}
                            {Boolean(deliberationResult.task_id) && (
                              <div>Task ID: {String(deliberationResult.task_id)}</div>
                            )}
                            {Boolean(deliberationResult.decision_type) && (
                              <div>Decision Type: {String(deliberationResult.decision_type)}</div>
                            )}
                            {deliberationResult.confidence !== undefined && (
                              <div>Confidence: {String(deliberationResult.confidence)}</div>
                            )}
                            {deliberationResult.consensus_reached !== undefined && (
                              <div>Consensus: {String(deliberationResult.consensus_reached)}</div>
                            )}
                            {Boolean(deliberationResult.request_id) && (
                              <button
                                className="mt-2 px-2 py-1 border border-border rounded text-xs text-text-muted hover:text-text"
                                onClick={checkDeliberationStatus}
                                disabled={deliberationLoading}
                              >
                                Check Status
                              </button>
                            )}
                          </div>
                        )}
                        {deliberationStatus && (
                          <div className="text-xs font-theme-data text-text-muted">
                            Status Update: {String(deliberationStatus.status || 'unknown')}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {/* Agents Tab - Enhanced with AgentCatalog */}
                {activeTab === 'agents' && (
                  <AgentCatalog
                    onSelectAgent={(_agent) => {
                      // Agent selection handler
                    }}
                    onConfigureAgent={(_agent) => {
                      // Agent configuration handler
                    }}
                  />
                )}

                {/* Workflows Tab */}
                {activeTab === 'workflows' && (
                  <div className="h-[calc(100vh-280px)]">
                    <WorkflowBuilder
                      onSave={() => {
                        // Workflow saved
                      }}
                      onExecute={(_executionId) => {
                        setActiveTab('executions');
                      }}
                    />
                  </div>
                )}

                {/* Knowledge Tab */}
                {activeTab === 'knowledge' && (
                  <KnowledgeExplorer
                    onSelectNode={(_node) => {
                      // Knowledge node selection handler
                    }}
                  />
                )}

                {/* Connectors Tab */}
                {activeTab === 'connectors' && (
                  <ConnectorDashboard
                    onSelectConnector={(_connector) => {
                      // Connector selection handler
                    }}
                  />
                )}

                {/* Executions Tab */}
                {activeTab === 'executions' && (
                  <ExecutionMonitor
                    onSelectExecution={(_execution) => {
                      // Execution selection handler
                    }}
                  />
                )}

                {/* Queue Tab */}
                {activeTab === 'queue' && (
                  <div className="space-y-4">
                    {/* Real-time indicator */}
                    {wsConnected && (
                      <div className="flex items-center gap-2 text-xs font-theme-data text-[var(--accent)] mb-2">
                        <span className="w-2 h-2 rounded-full bg-[var(--accent)] animate-pulse" />
                        Real-time updates via WebSocket
                        {recentFindings.length > 0 && (
                          <span className="ml-2 px-2 py-0.5 bg-[var(--accent)]/20 rounded">
                            {recentFindings.length} recent findings
                          </span>
                        )}
                      </div>
                    )}
                    {displayJobs.length === 0 ? (
                      <div className="card p-8 text-center">
                        <div className="font-theme-data text-text-muted">No jobs in queue</div>
                      </div>
                    ) : (
                      displayJobs.map((job) => (
                        <div key={job.id} className="card p-4">
                          <div className="flex items-start justify-between mb-3">
                            <div>
                              <div className="font-theme-data font-medium">{job.name}</div>
                              <div className="text-xs text-text-muted font-theme-data mt-1">
                                {job.type.replace('_', ' ').toUpperCase()} | {job.document_count}{' '}
                                documents
                              </div>
                            </div>
                            <div className="flex items-center gap-2">
                              <span
                                className={`text-xs font-theme-data uppercase ${getStatusColor(job.status)}`}
                              >
                                {job.status}
                              </span>
                            </div>
                          </div>

                          {(job.status === 'running' || job.status === 'paused') && (
                            <div className="mb-3">
                              <div className="h-1.5 bg-surface rounded overflow-hidden">
                                <div
                                  className={`h-full transition-all ${job.status === 'paused' ? 'bg-acid-yellow' : 'bg-[var(--acid-cyan)]'}`}
                                  style={{ width: `${job.progress * 100}%` }}
                                />
                              </div>
                              <div className="text-xs text-text-muted font-theme-data mt-1 text-right">
                                {Math.round(job.progress * 100)}%
                              </div>
                            </div>
                          )}

                          <div className="flex items-center justify-between">
                            <div className="text-xs font-theme-data text-text-muted">
                              {job.agents_assigned.length > 0 && (
                                <span>Agents: {job.agents_assigned.join(', ')}</span>
                              )}
                              {job.started_at && (
                                <span className="ml-4">
                                  Started: {new Date(job.started_at).toLocaleString()}
                                </span>
                              )}
                            </div>

                            {job.status !== 'completed' && job.status !== 'failed' && (
                              <div className="flex gap-2">
                                {job.status === 'running' && (
                                  <button
                                    onClick={() => pauseJob(job.id)}
                                    className="px-2 py-1 text-xs font-theme-data border border-border rounded hover:border-acid-yellow transition-colors"
                                  >
                                    Pause
                                  </button>
                                )}
                                {job.status === 'paused' && (
                                  <button
                                    onClick={() => resumeJob(job.id)}
                                    className="px-2 py-1 text-xs font-theme-data border border-border rounded hover:border-[var(--accent)] transition-colors"
                                  >
                                    Resume
                                  </button>
                                )}
                                <button
                                  onClick={() => cancelJob(job.id)}
                                  className="px-2 py-1 text-xs font-theme-data border border-[var(--crimson)]/30 text-[var(--crimson)] rounded hover:bg-[var(--crimson)]/10 transition-colors"
                                >
                                  Cancel
                                </button>
                              </div>
                            )}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                )}

                {/* Verticals Tab */}
                {activeTab === 'verticals' && (
                  <div className="space-y-6">
                    <VerticalSelector
                      apiBase={backendConfig.api}
                      selectedVertical={selectedVertical || 'general'}
                      onVerticalChange={setSelectedVertical}
                      compact
                    />
                    <div className="card p-3 flex flex-col gap-2 text-xs font-theme-data text-text-muted lg:flex-row lg:items-center lg:justify-between">
                      <span>
                        {verticalsData.length > 0
                          ? `${verticalsData.length} live vertical profiles available from /api/verticals`
                          : 'Using built-in vertical presets while backend vertical metadata is unavailable'}
                      </span>
                      <span>
                        Focus:{' '}
                        <span className="text-[var(--accent)]">
                          {(selectedVertical || 'general').toUpperCase()}
                        </span>
                      </span>
                    </div>
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                      <div className="h-[500px]">
                        <KnowledgeExplorer
                          onSelectNode={(_node) => {
                            // Vertical knowledge selection handler
                          }}
                          height={500}
                          showStats={false}
                          className="h-full"
                        />
                      </div>
                      <div className="h-[500px]">
                        <ExecutionMonitor
                          onSelectExecution={(_execution) => {
                            // Vertical execution selection handler
                          }}
                          className="h-full"
                        />
                      </div>
                    </div>
                  </div>
                )}

                {/* Policy Tab */}
                {activeTab === 'policy' && <PolicyDashboard />}

                {/* Workspace Tab */}
                {activeTab === 'workspace' && (
                  <WorkspaceManager
                    onWorkspaceSelect={(_workspace) => {
                      // Workspace selection handler
                    }}
                    onWorkspaceUpdate={(_workspace) => {
                      // Workspace update handler
                    }}
                  />
                )}

                {/* Health Tab */}
                {activeTab === 'health' && <SystemHealthDashboard apiUrl={backendConfig.api} />}

                {/* Settings Tab */}
                {activeTab === 'settings' && (
                  <div className="max-w-2xl space-y-6">
                    <div className="card p-4">
                      <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">
                        Processing Settings
                      </h3>
                      <div className="space-y-4">
                        <div className="flex items-center justify-between">
                          <div>
                            <div className="font-theme-data text-sm">Max Concurrent Documents</div>
                            <div className="text-xs text-text-muted">
                              Limit parallel document processing
                            </div>
                          </div>
                          <select className="bg-surface border border-border rounded px-3 py-1.5 text-sm font-theme-data">
                            <option>5</option>
                            <option>10</option>
                            <option>20</option>
                            <option>50</option>
                          </select>
                        </div>
                        <div className="flex items-center justify-between">
                          <div>
                            <div className="font-theme-data text-sm">Max Concurrent Chunks</div>
                            <div className="text-xs text-text-muted">
                              Chunks processed in parallel per job
                            </div>
                          </div>
                          <select className="bg-surface border border-border rounded px-3 py-1.5 text-sm font-theme-data">
                            <option>10</option>
                            <option>20</option>
                            <option>50</option>
                          </select>
                        </div>
                      </div>
                    </div>

                    <div className="card p-4">
                      <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">
                        Audit Settings
                      </h3>
                      <div className="space-y-4">
                        <div className="flex items-center justify-between">
                          <div>
                            <div className="font-theme-data text-sm">Primary Scan Model</div>
                            <div className="text-xs text-text-muted">
                              Model for initial document scanning
                            </div>
                          </div>
                          <select className="bg-surface border border-border rounded px-3 py-1.5 text-sm font-theme-data">
                            <option>gemini-3-pro</option>
                            <option>claude-3.5-sonnet</option>
                            <option>gpt-4-turbo</option>
                          </select>
                        </div>
                        <div className="flex items-center justify-between">
                          <div>
                            <div className="font-theme-data text-sm">Verification Model</div>
                            <div className="text-xs text-text-muted">
                              Model for finding verification
                            </div>
                          </div>
                          <select className="bg-surface border border-border rounded px-3 py-1.5 text-sm font-theme-data">
                            <option>claude-3.5-sonnet</option>
                            <option>gpt-4-turbo</option>
                          </select>
                        </div>
                        <div className="flex items-center justify-between">
                          <div>
                            <div className="font-theme-data text-sm">
                              Require Multi-Agent Confirmation
                            </div>
                            <div className="text-xs text-text-muted">
                              Findings must be verified by multiple agents
                            </div>
                          </div>
                          <label className="relative inline-flex items-center cursor-pointer">
                            <input type="checkbox" defaultChecked className="sr-only peer" />
                            <div className="w-11 h-6 bg-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-text-muted after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[var(--accent)]/30 peer-checked:after:bg-[var(--accent)]"></div>
                          </label>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // DASHBOARD</p>
        </footer>
      </main>
    </>
  );
}
