'use client';

/**
 * Execution Monitor Component
 *
 * Real-time monitoring of workflow execution with task progress,
 * agent communication visualization, and performance metrics.
 */

import { useState, useMemo } from 'react';

export type TaskStatus = 'pending' | 'ready' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface TaskExecution {
  id: string;
  stepId: string;
  workflowId: string;
  status: TaskStatus;
  progress?: number;
  startedAt?: string;
  completedAt?: string;
  executorId?: string;
  error?: string;
  result?: unknown;
}

export interface WorkflowExecution {
  id: string;
  name: string;
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  tasks: TaskExecution[];
  startedAt: string;
  completedAt?: string;
}

interface ExecutionMonitorProps {
  workflows?: WorkflowExecution[];
  selectedWorkflowId?: string;
  onWorkflowSelect?: (workflowId: string) => void;
  onTaskClick?: (task: TaskExecution) => void;
}

// Mock data for demonstration
const MOCK_WORKFLOWS: WorkflowExecution[] = [
  {
    id: 'wf_001',
    name: 'Code Review Pipeline',
    status: 'running',
    progress: 0.6,
    startedAt: '2024-01-16T10:30:00Z',
    tasks: [
      {
        id: 'task_001',
        stepId: 'security_scan',
        workflowId: 'wf_001',
        status: 'completed',
        startedAt: '2024-01-16T10:30:00Z',
        completedAt: '2024-01-16T10:32:00Z',
        executorId: 'executor_1',
      },
      {
        id: 'task_002',
        stepId: 'code_review',
        workflowId: 'wf_001',
        status: 'running',
        progress: 0.7,
        startedAt: '2024-01-16T10:32:00Z',
        executorId: 'executor_2',
      },
      { id: 'task_003', stepId: 'debate_findings', workflowId: 'wf_001', status: 'pending' },
      { id: 'task_004', stepId: 'generate_report', workflowId: 'wf_001', status: 'pending' },
    ],
  },
  {
    id: 'wf_002',
    name: 'Contract Analysis',
    status: 'completed',
    progress: 1.0,
    startedAt: '2024-01-16T09:00:00Z',
    completedAt: '2024-01-16T09:45:00Z',
    tasks: [
      {
        id: 'task_005',
        stepId: 'extract_clauses',
        workflowId: 'wf_002',
        status: 'completed',
        startedAt: '2024-01-16T09:00:00Z',
        completedAt: '2024-01-16T09:15:00Z',
      },
      {
        id: 'task_006',
        stepId: 'compliance_check',
        workflowId: 'wf_002',
        status: 'completed',
        startedAt: '2024-01-16T09:15:00Z',
        completedAt: '2024-01-16T09:30:00Z',
      },
      {
        id: 'task_007',
        stepId: 'risk_assessment',
        workflowId: 'wf_002',
        status: 'completed',
        startedAt: '2024-01-16T09:30:00Z',
        completedAt: '2024-01-16T09:45:00Z',
      },
    ],
  },
];

const STATUS_COLORS: Record<TaskStatus, string> = {
  pending: 'bg-gray-500',
  ready: 'bg-yellow-500',
  running: 'bg-cyan-500',
  completed: 'bg-[var(--accent)]',
  failed: 'bg-red-500',
  cancelled: 'bg-gray-400',
};

const STATUS_TEXT_COLORS: Record<TaskStatus, string> = {
  pending: 'text-gray-400',
  ready: 'text-yellow-400',
  running: 'text-cyan-400',
  completed: 'text-[var(--accent)]',
  failed: 'text-red-400',
  cancelled: 'text-gray-400',
};

export function ExecutionMonitor({
  workflows = MOCK_WORKFLOWS,
  onWorkflowSelect,
  onTaskClick,
}: ExecutionMonitorProps) {
  const [expandedWorkflowId, setExpandedWorkflowId] = useState<string | null>(
    workflows.length > 0 ? workflows[0].id : null,
  );

  const _selectedWorkflow = useMemo(() => {
    return workflows.find((w) => w.id === expandedWorkflowId);
  }, [workflows, expandedWorkflowId]);

  const stats = useMemo(() => {
    const running = workflows.filter((w) => w.status === 'running').length;
    const completed = workflows.filter((w) => w.status === 'completed').length;
    const failed = workflows.filter((w) => w.status === 'failed').length;
    const totalTasks = workflows.reduce((acc, w) => acc + w.tasks.length, 0);
    const completedTasks = workflows.reduce(
      (acc, w) => acc + w.tasks.filter((t) => t.status === 'completed').length,
      0,
    );

    return { running, completed, failed, totalTasks, completedTasks };
  }, [workflows]);

  const formatDuration = (start: string, end?: string) => {
    const startTime = new Date(start).getTime();
    const endTime = end ? new Date(end).getTime() : Date.now();
    const duration = Math.round((endTime - startTime) / 1000);

    if (duration < 60) return `${duration}s`;
    if (duration < 3600) return `${Math.floor(duration / 60)}m ${duration % 60}s`;
    return `${Math.floor(duration / 3600)}h ${Math.floor((duration % 3600) / 60)}m`;
  };

  return (
    <div className="bg-surface border border-border rounded-lg overflow-hidden h-full flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border bg-bg flex-shrink-0">
        <h3 className="text-sm font-theme-data font-bold text-[var(--accent)]">
          EXECUTION MONITOR
        </h3>
        <p className="text-xs text-text-muted mt-1">Real-time workflow and task execution status</p>
      </div>

      {/* Stats Bar */}
      <div className="grid grid-cols-5 gap-2 p-4 border-b border-border flex-shrink-0">
        <div className="text-center">
          <div className="text-xl font-bold text-cyan-400">{stats.running}</div>
          <div className="text-xs text-text-muted">Running</div>
        </div>
        <div className="text-center">
          <div className="text-xl font-bold text-[var(--accent)]">{stats.completed}</div>
          <div className="text-xs text-text-muted">Completed</div>
        </div>
        <div className="text-center">
          <div className="text-xl font-bold text-red-400">{stats.failed}</div>
          <div className="text-xs text-text-muted">Failed</div>
        </div>
        <div className="text-center">
          <div className="text-xl font-bold text-text">{stats.totalTasks}</div>
          <div className="text-xs text-text-muted">Total Tasks</div>
        </div>
        <div className="text-center">
          <div className="text-xl font-bold text-purple-400">
            {stats.totalTasks > 0 ? Math.round((stats.completedTasks / stats.totalTasks) * 100) : 0}
            %
          </div>
          <div className="text-xs text-text-muted">Progress</div>
        </div>
      </div>

      {/* Workflow List */}
      <div className="flex-1 overflow-y-auto">
        {workflows.length === 0 ? (
          <div className="text-center py-12 text-text-muted">
            <span className="text-4xl">📋</span>
            <p className="mt-4">No workflows running</p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {workflows.map((workflow) => (
              <div key={workflow.id} className="bg-bg">
                {/* Workflow Header */}
                <button
                  onClick={() => {
                    setExpandedWorkflowId(expandedWorkflowId === workflow.id ? null : workflow.id);
                    onWorkflowSelect?.(workflow.id);
                  }}
                  className="w-full px-4 py-3 flex items-center gap-3 hover:bg-surface transition-colors"
                >
                  {/* Status Indicator */}
                  <div
                    className={`
                      w-3 h-3 rounded-full
                      ${workflow.status === 'running' ? 'animate-pulse' : ''}
                      ${workflow.status === 'running' ? 'bg-cyan-400' : ''}
                      ${workflow.status === 'completed' ? 'bg-[var(--accent)]' : ''}
                      ${workflow.status === 'failed' ? 'bg-red-500' : ''}
                      ${workflow.status === 'cancelled' ? 'bg-gray-400' : ''}
                    `}
                  />

                  {/* Workflow Info */}
                  <div className="flex-1 text-left">
                    <div className="font-theme-data font-bold text-text">{workflow.name}</div>
                    <div className="text-xs text-text-muted">
                      {workflow.tasks.length} tasks •{' '}
                      {formatDuration(workflow.startedAt, workflow.completedAt)}
                    </div>
                  </div>

                  {/* Progress Bar */}
                  <div className="w-24">
                    <div className="h-2 bg-surface rounded-full overflow-hidden">
                      <div
                        className={`h-full transition-all duration-500 ${
                          workflow.status === 'completed'
                            ? 'bg-[var(--accent)]'
                            : workflow.status === 'failed'
                              ? 'bg-red-500'
                              : 'bg-cyan-400'
                        }`}
                        style={{ width: `${workflow.progress * 100}%` }}
                      />
                    </div>
                    <div className="text-xs text-text-muted text-center mt-1">
                      {Math.round(workflow.progress * 100)}%
                    </div>
                  </div>

                  {/* Expand Icon */}
                  <span
                    className={`text-text-muted transition-transform ${
                      expandedWorkflowId === workflow.id ? 'rotate-90' : ''
                    }`}
                  >
                    ▶
                  </span>
                </button>

                {/* Task List (expanded) */}
                {expandedWorkflowId === workflow.id && (
                  <div className="px-4 pb-4">
                    <div className="bg-surface border border-border rounded-lg overflow-hidden">
                      {workflow.tasks.map((task, index) => (
                        <div
                          key={task.id}
                          onClick={() => onTaskClick?.(task)}
                          className={`
                            px-4 py-2 flex items-center gap-3 cursor-pointer
                            hover:bg-bg transition-colors
                            ${index > 0 ? 'border-t border-border' : ''}
                          `}
                        >
                          {/* Task Status */}
                          <div className={`w-2 h-2 rounded-full ${STATUS_COLORS[task.status]}`} />

                          {/* Task Info */}
                          <div className="flex-1">
                            <div className="font-theme-data text-sm text-text">{task.stepId}</div>
                            <div className="text-xs text-text-muted">
                              {task.executorId && `${task.executorId} • `}
                              {task.startedAt && formatDuration(task.startedAt, task.completedAt)}
                            </div>
                          </div>

                          {/* Task Status Badge */}
                          <span
                            className={`
                              px-2 py-0.5 text-xs font-theme-data uppercase rounded
                              ${STATUS_TEXT_COLORS[task.status]}
                            `}
                          >
                            {task.status}
                          </span>

                          {/* Progress (for running tasks) */}
                          {task.status === 'running' && task.progress !== undefined && (
                            <div className="w-16 h-1.5 bg-bg rounded-full overflow-hidden">
                              <div
                                className="h-full bg-cyan-400 transition-all"
                                style={{ width: `${task.progress * 100}%` }}
                              />
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-2 border-t border-border bg-bg flex-shrink-0">
        <div className="flex items-center justify-between text-xs font-theme-data text-text-muted">
          <span>{workflows.length} workflows</span>
          <span className="text-cyan-400">{stats.running > 0 && `● ${stats.running} running`}</span>
        </div>
      </div>
    </div>
  );
}

export default ExecutionMonitor;
