'use client';

/**
 * Queue Monitoring Panel Component
 *
 * Provides real-time monitoring and management of the job queue system.
 * Allows viewing job status, retrying failed jobs, and cancelling pending jobs.
 */

import { useState, useMemo, useCallback } from 'react';

export type JobStatus =
  'pending' | 'processing' | 'completed' | 'failed' | 'cancelled' | 'retrying';

export interface QueueJob {
  id: string;
  status: JobStatus;
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  attempts: number;
  maxAttempts: number;
  priority: number;
  error?: string;
  workerId?: string;
  metadata: Record<string, unknown>;
}

export interface QueueStats {
  pending: number;
  processing: number;
  completed: number;
  failed: number;
  cancelled: number;
  retrying: number;
  streamLength: number;
  pendingInGroup: number;
}

export interface QueueWorker {
  workerId: string;
  group: string;
  pending: number;
  idleMs: number;
}

interface QueueMonitoringPanelProps {
  stats?: QueueStats;
  jobs?: QueueJob[];
  workers?: QueueWorker[];
  onRetryJob?: (jobId: string) => Promise<void>;
  onCancelJob?: (jobId: string) => Promise<void>;
  onRefresh?: () => void;
  isLoading?: boolean;
}

// Mock data for demonstration
const MOCK_STATS: QueueStats = {
  pending: 5,
  processing: 2,
  completed: 47,
  failed: 3,
  cancelled: 1,
  retrying: 1,
  streamLength: 58,
  pendingInGroup: 7,
};

const MOCK_JOBS: QueueJob[] = [
  {
    id: 'job_001',
    status: 'processing',
    createdAt: '2024-01-16T10:30:00Z',
    startedAt: '2024-01-16T10:31:00Z',
    attempts: 1,
    maxAttempts: 3,
    priority: 0,
    workerId: 'worker-1',
    metadata: { question: 'Analyze the security implications of...', rounds: 3 },
  },
  {
    id: 'job_002',
    status: 'pending',
    createdAt: '2024-01-16T10:35:00Z',
    attempts: 0,
    maxAttempts: 3,
    priority: 1,
    metadata: { question: 'Review the contract terms...', rounds: 3 },
  },
  {
    id: 'job_003',
    status: 'failed',
    createdAt: '2024-01-16T09:00:00Z',
    startedAt: '2024-01-16T09:01:00Z',
    completedAt: '2024-01-16T09:05:00Z',
    attempts: 3,
    maxAttempts: 3,
    priority: 0,
    error: 'Agent timeout after 300 seconds',
    metadata: { question: 'Complex financial analysis...', rounds: 5 },
  },
  {
    id: 'job_004',
    status: 'completed',
    createdAt: '2024-01-16T08:00:00Z',
    startedAt: '2024-01-16T08:01:00Z',
    completedAt: '2024-01-16T08:15:00Z',
    attempts: 1,
    maxAttempts: 3,
    priority: 0,
    workerId: 'worker-2',
    metadata: { question: 'Code review for authentication module', rounds: 3 },
  },
];

const MOCK_WORKERS: QueueWorker[] = [
  { workerId: 'worker-1', group: 'aragora-workers', pending: 1, idleMs: 0 },
  { workerId: 'worker-2', group: 'aragora-workers', pending: 0, idleMs: 5000 },
  { workerId: 'worker-3', group: 'aragora-workers', pending: 0, idleMs: 30000 },
];

const STATUS_COLORS: Record<JobStatus, string> = {
  pending: 'bg-yellow-500',
  processing: 'bg-cyan-500',
  completed: 'bg-[var(--accent)]',
  failed: 'bg-red-500',
  cancelled: 'bg-gray-400',
  retrying: 'bg-orange-500',
};

const STATUS_TEXT_COLORS: Record<JobStatus, string> = {
  pending: 'text-yellow-400',
  processing: 'text-cyan-400',
  completed: 'text-[var(--accent)]',
  failed: 'text-red-400',
  cancelled: 'text-gray-400',
  retrying: 'text-orange-400',
};

type TabType = 'jobs' | 'workers';

export function QueueMonitoringPanel({
  stats = MOCK_STATS,
  jobs = MOCK_JOBS,
  workers = MOCK_WORKERS,
  onRetryJob,
  onCancelJob,
  onRefresh,
  isLoading = false,
}: QueueMonitoringPanelProps) {
  const [activeTab, setActiveTab] = useState<TabType>('jobs');
  const [statusFilter, setStatusFilter] = useState<JobStatus | 'all'>('all');
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // Filter jobs by status
  const filteredJobs = useMemo(() => {
    if (statusFilter === 'all') return jobs;
    return jobs.filter((job) => job.status === statusFilter);
  }, [jobs, statusFilter]);

  const handleRetry = useCallback(
    async (jobId: string) => {
      if (!onRetryJob) return;
      setActionLoading(jobId);
      try {
        await onRetryJob(jobId);
      } finally {
        setActionLoading(null);
      }
    },
    [onRetryJob],
  );

  const handleCancel = useCallback(
    async (jobId: string) => {
      if (!onCancelJob) return;
      setActionLoading(jobId);
      try {
        await onCancelJob(jobId);
      } finally {
        setActionLoading(null);
      }
    },
    [onCancelJob],
  );

  const formatDuration = (start: string, end?: string) => {
    const startTime = new Date(start).getTime();
    const endTime = end ? new Date(end).getTime() : Date.now();
    const duration = Math.round((endTime - startTime) / 1000);

    if (duration < 60) return `${duration}s`;
    if (duration < 3600) return `${Math.floor(duration / 60)}m ${duration % 60}s`;
    return `${Math.floor(duration / 3600)}h ${Math.floor((duration % 3600) / 60)}m`;
  };

  const formatIdleTime = (ms: number) => {
    if (ms < 1000) return 'active';
    if (ms < 60000) return `${Math.round(ms / 1000)}s idle`;
    return `${Math.round(ms / 60000)}m idle`;
  };

  return (
    <div className="bg-surface border border-border rounded-lg overflow-hidden h-full flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border bg-bg flex-shrink-0 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-theme-data font-bold text-[var(--accent)]">QUEUE MONITOR</h3>
          <p className="text-xs text-text-muted mt-1">Job queue status and worker management</p>
        </div>
        {onRefresh && (
          <button
            onClick={onRefresh}
            disabled={isLoading}
            className="px-3 py-1 text-xs font-theme-data bg-bg border border-border rounded hover:border-[var(--accent)] transition-colors disabled:opacity-50"
          >
            {isLoading ? '...' : 'REFRESH'}
          </button>
        )}
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-6 gap-2 p-4 border-b border-border flex-shrink-0">
        <div className="text-center">
          <div className="text-xl font-bold text-yellow-400">{stats.pending}</div>
          <div className="text-xs text-text-muted">Pending</div>
        </div>
        <div className="text-center">
          <div className="text-xl font-bold text-cyan-400">{stats.processing}</div>
          <div className="text-xs text-text-muted">Processing</div>
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
          <div className="text-xl font-bold text-orange-400">{stats.retrying}</div>
          <div className="text-xs text-text-muted">Retrying</div>
        </div>
        <div className="text-center">
          <div className="text-xl font-bold text-text">{stats.streamLength}</div>
          <div className="text-xs text-text-muted">Total</div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border flex-shrink-0">
        {(['jobs', 'workers'] as TabType[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`
              px-4 py-2 text-xs font-theme-data uppercase
              ${
                activeTab === tab
                  ? 'text-[var(--accent)] border-b-2 border-[var(--accent)] bg-bg'
                  : 'text-text-muted hover:text-text'
              }
            `}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Jobs Tab */}
      {activeTab === 'jobs' && (
        <>
          {/* Status Filter */}
          <div className="p-4 border-b border-border flex-shrink-0">
            <div className="flex items-center gap-2">
              <span className="text-xs font-theme-data text-text-muted">Filter:</span>
              {(['all', 'pending', 'processing', 'failed', 'completed'] as const).map((status) => (
                <button
                  key={status}
                  onClick={() => setStatusFilter(status)}
                  className={`
                      px-2 py-1 text-xs font-theme-data rounded
                      ${
                        statusFilter === status
                          ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                          : 'bg-bg border border-border hover:border-text-muted'
                      }
                    `}
                >
                  {status.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          {/* Job List */}
          <div className="flex-1 overflow-y-auto">
            {filteredJobs.length === 0 ? (
              <div className="text-center py-12 text-text-muted">
                <span className="text-4xl">📭</span>
                <p className="mt-4">No jobs found</p>
              </div>
            ) : (
              <div className="divide-y divide-border">
                {filteredJobs.map((job) => (
                  <div key={job.id} className="bg-bg">
                    {/* Job Header */}
                    <button
                      onClick={() => setExpandedJobId(expandedJobId === job.id ? null : job.id)}
                      className="w-full px-4 py-3 flex items-center gap-3 hover:bg-surface transition-colors"
                    >
                      {/* Status Indicator */}
                      <div
                        className={`
                          w-3 h-3 rounded-full
                          ${job.status === 'processing' ? 'animate-pulse' : ''}
                          ${STATUS_COLORS[job.status]}
                        `}
                      />

                      {/* Job Info */}
                      <div className="flex-1 text-left">
                        <div className="font-theme-data text-sm text-text">{job.id}</div>
                        <div className="text-xs text-text-muted truncate max-w-md">
                          {(job.metadata?.question as string) || 'No description'}
                        </div>
                      </div>

                      {/* Attempts */}
                      <span className="text-xs font-theme-data text-text-muted">
                        {job.attempts}/{job.maxAttempts}
                      </span>

                      {/* Status Badge */}
                      <span
                        className={`
                          px-2 py-0.5 text-xs font-theme-data uppercase rounded
                          ${STATUS_TEXT_COLORS[job.status]}
                        `}
                      >
                        {job.status}
                      </span>

                      {/* Expand Icon */}
                      <span
                        className={`text-text-muted transition-transform ${
                          expandedJobId === job.id ? 'rotate-90' : ''
                        }`}
                      >
                        ▶
                      </span>
                    </button>

                    {/* Expanded Details */}
                    {expandedJobId === job.id && (
                      <div className="px-4 pb-4">
                        <div className="bg-surface border border-border rounded-lg p-4">
                          <div className="grid grid-cols-2 gap-4 text-xs">
                            <div>
                              <span className="text-text-muted">Created:</span>
                              <p className="font-theme-data">
                                {new Date(job.createdAt).toLocaleString()}
                              </p>
                            </div>
                            {job.startedAt && (
                              <div>
                                <span className="text-text-muted">Duration:</span>
                                <p className="font-theme-data">
                                  {formatDuration(job.startedAt, job.completedAt)}
                                </p>
                              </div>
                            )}
                            {job.workerId && (
                              <div>
                                <span className="text-text-muted">Worker:</span>
                                <p className="font-theme-data text-cyan-400">{job.workerId}</p>
                              </div>
                            )}
                            <div>
                              <span className="text-text-muted">Priority:</span>
                              <p className="font-theme-data">{job.priority}</p>
                            </div>
                          </div>

                          {job.error && (
                            <div className="mt-3 p-2 bg-red-500/10 border border-red-500/20 rounded">
                              <span className="text-xs text-red-400 font-theme-data">
                                Error: {job.error}
                              </span>
                            </div>
                          )}

                          {/* Actions */}
                          <div className="mt-4 flex gap-2">
                            {(job.status === 'failed' || job.status === 'cancelled') &&
                              onRetryJob && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleRetry(job.id);
                                  }}
                                  disabled={actionLoading === job.id}
                                  className="px-3 py-1 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/50 rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
                                >
                                  {actionLoading === job.id ? '...' : 'RETRY'}
                                </button>
                              )}
                            {(job.status === 'pending' || job.status === 'retrying') &&
                              onCancelJob && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleCancel(job.id);
                                  }}
                                  disabled={actionLoading === job.id}
                                  className="px-3 py-1 text-xs font-theme-data bg-red-500/20 text-red-400 border border-red-500/50 rounded hover:bg-red-500/30 transition-colors disabled:opacity-50"
                                >
                                  {actionLoading === job.id ? '...' : 'CANCEL'}
                                </button>
                              )}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {/* Workers Tab */}
      {activeTab === 'workers' && (
        <div className="flex-1 overflow-y-auto p-4">
          {workers.length === 0 ? (
            <div className="text-center py-12 text-text-muted">
              <span className="text-4xl">👷</span>
              <p className="mt-4">No workers connected</p>
            </div>
          ) : (
            <div className="space-y-2">
              {workers.map((worker) => (
                <div
                  key={worker.workerId}
                  className="p-3 bg-bg border border-border rounded-lg flex items-center gap-4"
                >
                  {/* Worker Status */}
                  <div
                    className={`
                      w-3 h-3 rounded-full
                      ${worker.pending > 0 ? 'bg-cyan-400 animate-pulse' : 'bg-[var(--accent)]'}
                    `}
                  />

                  {/* Worker Info */}
                  <div className="flex-1">
                    <div className="font-theme-data text-sm text-text">{worker.workerId}</div>
                    <div className="text-xs text-text-muted">{worker.group}</div>
                  </div>

                  {/* Pending Jobs */}
                  <div className="text-center">
                    <div className="text-lg font-bold text-cyan-400">{worker.pending}</div>
                    <div className="text-xs text-text-muted">Pending</div>
                  </div>

                  {/* Idle Status */}
                  <span
                    className={`
                      px-2 py-0.5 text-xs font-theme-data rounded
                      ${
                        worker.idleMs < 1000
                          ? 'text-[var(--accent)]'
                          : worker.idleMs < 60000
                            ? 'text-yellow-400'
                            : 'text-text-muted'
                      }
                    `}
                  >
                    {formatIdleTime(worker.idleMs)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="px-4 py-2 border-t border-border bg-bg flex-shrink-0">
        <div className="flex items-center justify-between text-xs font-theme-data text-text-muted">
          <span>
            {activeTab === 'jobs' && `${filteredJobs.length} jobs`}
            {activeTab === 'workers' && `${workers.length} workers`}
          </span>
          <span className="text-cyan-400">
            {stats.processing > 0 && `● ${stats.processing} processing`}
          </span>
        </div>
      </div>
    </div>
  );
}

export default QueueMonitoringPanel;
