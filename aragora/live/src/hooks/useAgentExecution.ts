import { useState, useCallback, useEffect, useRef } from 'react';
import { apiFetch } from '@/lib/api';
import type { AgentStatus } from '@/components/mission-control/AgentCard';

interface ApprovalRequest {
  agentId: string;
  agentName: string;
  taskDescription: string;
  diffPreview?: string;
  testResults?: { passed: number; failed: number; skipped: number };
  requestedAt: number;
}

interface UseAgentExecutionReturn {
  agents: AgentStatus[];
  approvalRequests: ApprovalRequest[];
  isLoading: boolean;
  approve: (agentId: string, notes?: string) => Promise<void>;
  reject: (agentId: string, feedback: string) => Promise<void>;
  dismissApproval: (agentId: string) => void;
  refresh: () => Promise<void>;
}

/**
 * Hook for tracking agent execution status and handling approval gates.
 * Combines polling of agent status with spectate WebSocket events.
 */
export function useAgentExecution(pipelineId: string | null): UseAgentExecutionReturn {
  const [agents, setAgents] = useState<AgentStatus[]>([]);
  const [approvalRequests, setApprovalRequests] = useState<ApprovalRequest[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const refresh = useCallback(async () => {
    if (!pipelineId) return;
    setIsLoading(true);
    try {
      const data = await apiFetch<{ agents?: Record<string, unknown>[] }>(
        `/api/v1/pipeline/${pipelineId}/agents`,
      );
      const agentList: AgentStatus[] = (data.agents || []).map((a: Record<string, unknown>) => ({
        id: a.id as string,
        name: (a.name as string) || (a.agent_name as string) || 'Unknown',
        agentType: (a.agent_type as string) || 'default',
        currentTask: a.current_task as string | undefined,
        status: (a.status as AgentStatus['status']) || 'pending',
        progress: (a.progress as number) || 0,
        worktreePath: a.worktree_path as string | undefined,
        diffPreview: a.diff_preview as string | undefined,
        phase: a.phase as AgentStatus['phase'] | undefined,
        duration: a.duration as number | undefined,
        error: a.error as string | undefined,
      }));
      setAgents(agentList);

      // Extract approval requests from agents awaiting approval
      const newApprovals = agentList
        .filter((a) => a.status === 'awaiting_approval')
        .map((a) => ({
          agentId: a.id,
          agentName: a.name,
          taskDescription: a.currentTask || '',
          diffPreview: a.diffPreview,
          requestedAt: Date.now(),
        }));
      setApprovalRequests((prev) => {
        const existingIds = new Set(prev.map((p) => p.agentId));
        const fresh = newApprovals.filter((a) => !existingIds.has(a.agentId));
        return [...prev, ...fresh];
      });
    } catch {
      // Silent failure - will retry on next poll
    } finally {
      setIsLoading(false);
    }
  }, [pipelineId]);

  const approve = useCallback(
    async (agentId: string, notes?: string) => {
      if (!pipelineId) return;
      await apiFetch(`/api/v1/pipeline/${pipelineId}/agents/${agentId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes }),
      });
      setApprovalRequests((prev) => prev.filter((r) => r.agentId !== agentId));
      await refresh();
    },
    [pipelineId, refresh],
  );

  const reject = useCallback(
    async (agentId: string, feedback: string) => {
      if (!pipelineId) return;
      await apiFetch(`/api/v1/pipeline/${pipelineId}/agents/${agentId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feedback }),
      });
      setApprovalRequests((prev) => prev.filter((r) => r.agentId !== agentId));
      await refresh();
    },
    [pipelineId, refresh],
  );

  const dismissApproval = useCallback((agentId: string) => {
    setApprovalRequests((prev) => prev.filter((r) => r.agentId !== agentId));
  }, []);

  // Connect to spectate WebSocket for real-time updates
  useEffect(() => {
    if (!pipelineId) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/spectate?pipeline_id=${pipelineId}`;

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          const type = msg.type || msg.event_type;

          if (
            type === 'assignment_started' ||
            type === 'assignment_completed' ||
            type === 'assignment_failed' ||
            type === 'approval_requested' ||
            type === 'agent_progress' ||
            type === 'pipeline_agent_assigned'
          ) {
            // Refresh agent list on relevant events
            refresh();
          }
        } catch {
          // Ignore parse errors
        }
      };

      ws.onerror = () => {
        // Fall back to polling
      };
    } catch {
      // WebSocket not available, rely on polling
    }

    // Poll every 5 seconds as fallback
    const interval = setInterval(refresh, 5000);
    refresh();

    return () => {
      clearInterval(interval);
      wsRef.current?.close();
    };
  }, [pipelineId, refresh]);

  return { agents, approvalRequests, isLoading, approve, reject, dismissApproval, refresh };
}
