'use client';

import { useState, useCallback, useMemo } from 'react';
import { PanelTemplate } from '@/components/shared/PanelTemplate';
import { useWorkflowExecution } from '@/hooks/useWorkflowExecution';
import { ExecutionTimeline } from './ExecutionTimeline';
import { ApprovalQueue } from './ApprovalQueue';
import type { WorkflowExecution, ApprovalRequest } from '@/hooks/useWorkflowExecution';

export type MonitorTab = 'active' | 'recent' | 'approvals';

export interface ExecutionMonitorProps {
  /** Initial tab to show */
  initialTab?: MonitorTab;
  /** Callback when an execution is selected */
  onSelectExecution?: (execution: WorkflowExecution) => void;
  /** Callback when an approval is completed */
  onApprovalComplete?: (request: ApprovalRequest, approved: boolean) => void;
  /** Maximum recent executions to show */
  maxRecent?: number;
  /** Auto-connect to execution stream */
  autoConnect?: boolean;
  /** Custom CSS classes */
  className?: string;
}

/**
 * Execution Monitor component for tracking workflow executions.
 * Provides real-time updates, timeline views, and approval handling.
 */
export function ExecutionMonitor({
  initialTab = 'active',
  onSelectExecution,
  onApprovalComplete,
  maxRecent = 10,
  autoConnect = true,
  className = '',
}: ExecutionMonitorProps) {
  const [activeTab, setActiveTab] = useState<MonitorTab>(initialTab);
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(null);
  const [approvalLoading, setApprovalLoading] = useState<Record<string, boolean>>({});

  // Execution hook
  const {
    activeExecutions,
    recentExecutions,
    approvalQueue,
    isConnected,
    connectionError,
    selectedExecution,
    selectExecution,
    terminateExecution,
    resolveApproval,
    connect,
    loadExecutions,
  } = useWorkflowExecution({
    autoConnect,
    onApprovalRequired: (_request) => {
      // Auto-switch to approvals tab when new approval comes in
      if (activeTab !== 'approvals') {
        // Could show a notification instead
      }
    },
  });

  // Handle execution selection
  const handleSelectExecution = useCallback(
    (execution: WorkflowExecution) => {
      setSelectedExecutionId(execution.id);
      selectExecution(execution.id);
      onSelectExecution?.(execution);
    },
    [selectExecution, onSelectExecution],
  );

  // Handle terminate
  const handleTerminate = useCallback(
    async (executionId: string) => {
      if (confirm('Are you sure you want to terminate this execution?')) {
        await terminateExecution(executionId);
      }
    },
    [terminateExecution],
  );

  // Handle approval
  const handleResolveApproval = useCallback(
    async (requestId: string, approved: boolean, notes?: string) => {
      setApprovalLoading((prev) => ({ ...prev, [requestId]: true }));
      try {
        await resolveApproval(requestId, approved, notes);
        const request = approvalQueue.find((r) => r.id === requestId);
        if (request) {
          onApprovalComplete?.(request, approved);
        }
      } finally {
        setApprovalLoading((prev) => ({ ...prev, [requestId]: false }));
      }
    },
    [resolveApproval, approvalQueue, onApprovalComplete],
  );

  // Limited recent executions
  const limitedRecent = useMemo(
    () => recentExecutions.slice(0, maxRecent),
    [recentExecutions, maxRecent],
  );

  // Execution list item
  const ExecutionItem = useCallback(
    ({
      execution,
      showActions = false,
    }: {
      execution: WorkflowExecution;
      showActions?: boolean;
    }) => {
      const isSelected = selectedExecutionId === execution.id;
      const completedSteps = execution.steps.filter((s) => s.status === 'completed').length;
      const progress =
        execution.steps.length > 0
          ? Math.round((completedSteps / execution.steps.length) * 100)
          : 0;

      const statusColors: Record<string, { bg: string; text: string }> = {
        pending: { bg: 'bg-gray-900/20', text: 'text-gray-400' },
        running: { bg: 'bg-blue-900/20', text: 'text-blue-400' },
        paused: { bg: 'bg-yellow-900/20', text: 'text-yellow-400' },
        waiting_approval: { bg: 'bg-purple-900/20', text: 'text-purple-400' },
        completed: { bg: 'bg-green-900/20', text: 'text-green-400' },
        failed: { bg: 'bg-red-900/20', text: 'text-red-400' },
        terminated: { bg: 'bg-gray-900/20', text: 'text-gray-400' },
      };

      const colors = statusColors[execution.status] || statusColors.pending;

      return (
        <div
          onClick={() => handleSelectExecution(execution)}
          className={`
            p-3 rounded-lg border cursor-pointer transition-all
            ${isSelected ? 'border-[var(--accent)] bg-[var(--accent)]/10' : 'border-border hover:border-text-muted'}
          `}
        >
          {/* Header */}
          <div className="flex items-start justify-between mb-2">
            <div>
              <div className="text-sm font-theme-data text-text">{execution.workflow_name}</div>
              <div className="text-xs text-text-muted">
                Started {new Date(execution.started_at).toLocaleString()}
              </div>
            </div>
            <div className={`px-2 py-1 text-xs rounded ${colors.bg} ${colors.text}`}>
              {execution.status.replace('_', ' ')}
            </div>
          </div>

          {/* Progress bar */}
          {execution.status === 'running' && (
            <div className="mb-2">
              <div className="flex items-center justify-between text-xs text-text-muted mb-1">
                <span>{execution.current_step || 'Initializing...'}</span>
                <span>{progress}%</span>
              </div>
              <div className="h-1 bg-surface rounded-full overflow-hidden">
                <div
                  className="h-full bg-[var(--accent)] transition-all"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}

          {/* Stats */}
          <div className="flex items-center gap-4 text-xs text-text-muted">
            <span>{execution.steps.length} steps</span>
            {execution.total_tokens_used !== undefined && (
              <span>{execution.total_tokens_used.toLocaleString()} tokens</span>
            )}
            {execution.total_cost_usd !== undefined && (
              <span>${execution.total_cost_usd.toFixed(4)}</span>
            )}
            {execution.duration_ms !== undefined && (
              <span>{(execution.duration_ms / 1000).toFixed(1)}s</span>
            )}
          </div>

          {/* Actions */}
          {showActions && execution.status === 'running' && (
            <div className="mt-3 flex justify-end">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleTerminate(execution.id);
                }}
                className="text-xs text-red-400 hover:text-red-300 transition-colors"
              >
                Terminate
              </button>
            </div>
          )}
        </div>
      );
    },
    [selectedExecutionId, handleSelectExecution, handleTerminate],
  );

  // Tab content
  const tabContent: Record<MonitorTab, React.ReactNode> = {
    active: (
      <div className="space-y-3">
        {activeExecutions.length === 0 ? (
          <div className="text-center py-8">
            <div className="text-4xl mb-2">⏸</div>
            <p className="text-text-muted">No active executions</p>
          </div>
        ) : (
          activeExecutions.map((execution) => (
            <ExecutionItem key={execution.id} execution={execution} showActions />
          ))
        )}
      </div>
    ),

    recent: (
      <div className="space-y-3">
        {limitedRecent.length === 0 ? (
          <div className="text-center py-8">
            <div className="text-4xl mb-2">📋</div>
            <p className="text-text-muted">No recent executions</p>
          </div>
        ) : (
          limitedRecent.map((execution) => (
            <ExecutionItem key={execution.id} execution={execution} />
          ))
        )}
      </div>
    ),

    approvals: (
      <ApprovalQueue
        requests={approvalQueue}
        onResolve={handleResolveApproval}
        loadingStates={approvalLoading}
      />
    ),
  };

  // Selected execution detail (if any)
  const detailPanel = selectedExecution && (
    <div className="mt-4 border-t border-border pt-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-theme-data text-text-muted">Execution Timeline</h4>
        <button
          onClick={() => selectExecution(null)}
          className="text-xs text-text-muted hover:text-text"
        >
          Close
        </button>
      </div>
      <ExecutionTimeline
        steps={selectedExecution.steps}
        currentStepId={selectedExecution.current_step}
      />
    </div>
  );

  return (
    <PanelTemplate
      title="Execution Monitor"
      icon="📊"
      onRefresh={() => loadExecutions()}
      badge={isConnected ? '● Live' : connectionError ? '● Error' : '○ Offline'}
      className={className}
      headerActions={
        !isConnected && (
          <button onClick={connect} className="text-xs text-[var(--accent)] hover:underline">
            Connect
          </button>
        )
      }
      tabs={[
        {
          id: 'active',
          label: 'Active',
          badge: activeExecutions.length,
          content: tabContent.active,
        },
        { id: 'recent', label: 'Recent', badge: limitedRecent.length, content: tabContent.recent },
        {
          id: 'approvals',
          label: 'Approvals',
          badge: approvalQueue.length,
          content: tabContent.approvals,
        },
      ]}
      activeTab={activeTab}
      onTabChange={(tab) => setActiveTab(tab as MonitorTab)}
    >
      {detailPanel}
    </PanelTemplate>
  );
}

export default ExecutionMonitor;
