'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';

interface QueueStats {
  pending: number;
  processing: number;
  completed: number;
  failed: number;
  cancelled: number;
  retrying: number;
  stream_length: number;
  pending_in_group: number;
}

interface QueueJob {
  id: string;
  job_type: string;
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled' | 'retrying';
  priority: 'low' | 'normal' | 'high' | 'critical';
  payload: Record<string, unknown>;
  result?: Record<string, unknown>;
  error?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  attempts: number;
  max_attempts: number;
}

interface Worker {
  name: string;
  pending: number;
  idle_time_ms: number;
  last_delivery?: string;
}

function StatusBadge({ status }: { status: QueueJob['status'] }) {
  const colors: Record<string, string> = {
    pending: 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/40',
    processing: 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40',
    completed: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40',
    failed: 'bg-acid-red/20 text-acid-red border-acid-red/40',
    cancelled: 'bg-text-muted/20 text-text-muted border-text-muted/40',
    retrying: 'bg-acid-magenta/20 text-[var(--acid-magenta)] border-acid-magenta/40',
  };

  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data rounded border ${colors[status] || colors.pending}`}
    >
      {status.toUpperCase()}
    </span>
  );
}

function PriorityBadge({ priority }: { priority: QueueJob['priority'] }) {
  const colors: Record<string, string> = {
    low: 'text-text-muted',
    normal: 'text-text',
    high: 'text-[var(--acid-yellow)]',
    critical: 'text-acid-red',
  };

  return (
    <span className={`text-xs font-theme-data ${colors[priority]}`}>{priority.toUpperCase()}</span>
  );
}

function StatsCard({
  label,
  value,
  color = 'acid-green',
}: {
  label: string;
  value: number;
  color?: string;
}) {
  return (
    <div className="card p-4">
      <div className={`text-2xl font-theme-data text-${color}`}>{value.toLocaleString()}</div>
      <div className="text-xs font-theme-data text-text-muted">{label}</div>
    </div>
  );
}

export default function QueueAdminPage() {
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();
  const token = tokens?.access_token;

  const [stats, setStats] = useState<QueueStats | null>(null);
  const [jobs, setJobs] = useState<QueueJob[]>([]);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [refreshInterval, setRefreshInterval] = useState<number>(10000);
  const [selectedJob, setSelectedJob] = useState<QueueJob | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};

      // Fetch stats
      const statsRes = await fetch(`${backendConfig.api}/api/queue/stats`, { headers });
      if (statsRes.ok) {
        const data = await statsRes.json();
        setStats(data.stats);
      }

      // Fetch jobs
      const jobsParams = new URLSearchParams({ limit: '50' });
      if (statusFilter) jobsParams.set('status', statusFilter);
      const jobsRes = await fetch(`${backendConfig.api}/api/queue/jobs?${jobsParams}`, { headers });
      if (jobsRes.ok) {
        const data = await jobsRes.json();
        setJobs(data.jobs || []);
      }

      // Fetch workers
      const workersRes = await fetch(`${backendConfig.api}/api/queue/workers`, { headers });
      if (workersRes.ok) {
        const data = await workersRes.json();
        setWorkers(data.workers || []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch queue data');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, token, statusFilter]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchData, refreshInterval]);

  const handleRetryJob = async (jobId: string) => {
    setActionLoading(jobId);
    try {
      const headers: HeadersInit = {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      };
      const res = await fetch(`${backendConfig.api}/api/queue/jobs/${jobId}/retry`, {
        method: 'POST',
        headers,
      });
      if (res.ok) {
        fetchData();
      }
    } finally {
      setActionLoading(null);
    }
  };

  const handleCancelJob = async (jobId: string) => {
    if (!confirm('Cancel this job?')) return;
    setActionLoading(jobId);
    try {
      const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};
      const res = await fetch(`${backendConfig.api}/api/queue/jobs/${jobId}`, {
        method: 'DELETE',
        headers,
      });
      if (res.ok) {
        fetchData();
      }
    } finally {
      setActionLoading(null);
    }
  };

  const formatDuration = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  };

  const formatDate = (date: string) => {
    return new Date(date).toLocaleString();
  };

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Header */}
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/" aria-label="Go to dashboard">
              <AsciiBannerCompact connected={true} />
            </Link>
            <nav className="flex items-center gap-3">
              <Link
                href="/admin"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [ADMIN]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </nav>
          </div>
        </header>

        <div className="container mx-auto px-4 py-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-2xl font-theme-data text-[var(--accent)]">Queue Management</h1>
              <p className="text-text-muted font-theme-data text-sm">
                Monitor and manage the job queue
              </p>
            </div>
            <div className="flex items-center gap-4">
              <select
                value={refreshInterval}
                onChange={(e) => setRefreshInterval(Number(e.target.value))}
                className="bg-surface border border-[var(--accent)]/30 rounded px-3 py-1 font-theme-data text-sm"
                aria-label="Refresh interval"
              >
                <option value={5000}>Refresh: 5s</option>
                <option value={10000}>Refresh: 10s</option>
                <option value={30000}>Refresh: 30s</option>
                <option value={60000}>Refresh: 60s</option>
              </select>
              <button
                onClick={fetchData}
                className="px-3 py-1 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30"
              >
                Refresh Now
              </button>
            </div>
          </div>

          {error && (
            <div className="mb-6 p-4 bg-acid-red/10 border border-acid-red/30 rounded">
              <p className="font-theme-data text-sm text-acid-red">{error}</p>
            </div>
          )}

          {/* Stats Overview */}
          {stats && (
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-4 mb-6">
              <StatsCard label="Pending" value={stats.pending} color="acid-cyan" />
              <StatsCard label="Processing" value={stats.processing} color="acid-yellow" />
              <StatsCard label="Completed" value={stats.completed} color="acid-green" />
              <StatsCard label="Failed" value={stats.failed} color="acid-red" />
              <StatsCard label="Cancelled" value={stats.cancelled} color="text-muted" />
              <StatsCard label="Retrying" value={stats.retrying} color="acid-magenta" />
              <StatsCard label="Stream" value={stats.stream_length} />
              <StatsCard label="In Group" value={stats.pending_in_group} />
            </div>
          )}

          {/* Workers */}
          {workers.length > 0 && (
            <div className="card p-4 mb-6">
              <h2 className="font-theme-data text-[var(--accent)] mb-3">
                Workers ({workers.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
                {workers.map((worker) => (
                  <div
                    key={worker.name}
                    className="bg-surface p-3 rounded border border-[var(--accent)]/20"
                  >
                    <div className="font-theme-data text-sm text-text truncate">{worker.name}</div>
                    <div className="flex justify-between mt-1">
                      <span className="font-theme-data text-xs text-text-muted">
                        Pending: {worker.pending}
                      </span>
                      <span className="font-theme-data text-xs text-text-muted">
                        Idle: {formatDuration(worker.idle_time_ms)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Jobs Filter */}
          <div className="flex items-center gap-4 mb-4">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm"
              aria-label="Filter by status"
            >
              <option value="">All Status</option>
              <option value="pending">Pending</option>
              <option value="processing">Processing</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
              <option value="cancelled">Cancelled</option>
              <option value="retrying">Retrying</option>
            </select>
            <span className="font-theme-data text-sm text-text-muted">{jobs.length} jobs</span>
          </div>

          {/* Jobs Table */}
          <div className="card overflow-hidden">
            {loading && jobs.length === 0 ? (
              <div className="p-8 text-center">
                <div className="font-theme-data text-text-muted animate-pulse">
                  Loading queue data...
                </div>
              </div>
            ) : jobs.length === 0 ? (
              <div className="p-8 text-center">
                <div className="font-theme-data text-text-muted">No jobs found</div>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-[var(--accent)]/20 text-left">
                      <th className="p-3 font-theme-data text-xs text-text-muted">ID</th>
                      <th className="p-3 font-theme-data text-xs text-text-muted">Type</th>
                      <th className="p-3 font-theme-data text-xs text-text-muted">Status</th>
                      <th className="p-3 font-theme-data text-xs text-text-muted">Priority</th>
                      <th className="p-3 font-theme-data text-xs text-text-muted">Attempts</th>
                      <th className="p-3 font-theme-data text-xs text-text-muted">Created</th>
                      <th className="p-3 font-theme-data text-xs text-text-muted">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((job) => (
                      <tr
                        key={job.id}
                        className="border-b border-[var(--accent)]/10 hover:bg-surface/50 cursor-pointer"
                        onClick={() => setSelectedJob(job)}
                      >
                        <td
                          className="p-3 font-theme-data text-sm text-text truncate max-w-[150px]"
                          title={job.id}
                        >
                          {job.id.slice(0, 12)}...
                        </td>
                        <td className="p-3 font-theme-data text-sm text-text">{job.job_type}</td>
                        <td className="p-3">
                          <StatusBadge status={job.status} />
                        </td>
                        <td className="p-3">
                          <PriorityBadge priority={job.priority} />
                        </td>
                        <td className="p-3 font-theme-data text-sm text-text">
                          {job.attempts}/{job.max_attempts}
                        </td>
                        <td className="p-3 font-theme-data text-xs text-text-muted">
                          {formatDate(job.created_at)}
                        </td>
                        <td className="p-3">
                          <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
                            {job.status === 'failed' && (
                              <button
                                onClick={() => handleRetryJob(job.id)}
                                disabled={actionLoading === job.id}
                                className="px-2 py-1 text-xs font-theme-data text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 rounded disabled:opacity-50"
                              >
                                Retry
                              </button>
                            )}
                            {(job.status === 'pending' || job.status === 'processing') && (
                              <button
                                onClick={() => handleCancelJob(job.id)}
                                disabled={actionLoading === job.id}
                                className="px-2 py-1 text-xs font-theme-data text-acid-red hover:bg-acid-red/10 rounded disabled:opacity-50"
                              >
                                Cancel
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Job Detail Modal */}
        {selectedJob && (
          <div
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
            onClick={() => setSelectedJob(null)}
          >
            <div
              className="bg-bg border border-[var(--accent)]/30 rounded-lg max-w-2xl w-full max-h-[80vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="p-4 border-b border-[var(--accent)]/20 flex justify-between items-center">
                <h3 className="font-theme-data text-[var(--accent)]">Job Details</h3>
                <button
                  onClick={() => setSelectedJob(null)}
                  className="text-text-muted hover:text-text"
                  aria-label="Close"
                >
                  [X]
                </button>
              </div>
              <div className="p-4 space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="font-theme-data text-xs text-text-muted">ID</label>
                    <div className="font-theme-data text-sm text-text break-all">
                      {selectedJob.id}
                    </div>
                  </div>
                  <div>
                    <label className="font-theme-data text-xs text-text-muted">Type</label>
                    <div className="font-theme-data text-sm text-text">{selectedJob.job_type}</div>
                  </div>
                  <div>
                    <label className="font-theme-data text-xs text-text-muted">Status</label>
                    <div className="mt-1">
                      <StatusBadge status={selectedJob.status} />
                    </div>
                  </div>
                  <div>
                    <label className="font-theme-data text-xs text-text-muted">Priority</label>
                    <div className="mt-1">
                      <PriorityBadge priority={selectedJob.priority} />
                    </div>
                  </div>
                  <div>
                    <label className="font-theme-data text-xs text-text-muted">Attempts</label>
                    <div className="font-theme-data text-sm text-text">
                      {selectedJob.attempts} / {selectedJob.max_attempts}
                    </div>
                  </div>
                  <div>
                    <label className="font-theme-data text-xs text-text-muted">Created</label>
                    <div className="font-theme-data text-sm text-text">
                      {formatDate(selectedJob.created_at)}
                    </div>
                  </div>
                  {selectedJob.started_at && (
                    <div>
                      <label className="font-theme-data text-xs text-text-muted">Started</label>
                      <div className="font-theme-data text-sm text-text">
                        {formatDate(selectedJob.started_at)}
                      </div>
                    </div>
                  )}
                  {selectedJob.completed_at && (
                    <div>
                      <label className="font-theme-data text-xs text-text-muted">Completed</label>
                      <div className="font-theme-data text-sm text-text">
                        {formatDate(selectedJob.completed_at)}
                      </div>
                    </div>
                  )}
                </div>

                {selectedJob.error && (
                  <div>
                    <label className="font-theme-data text-xs text-text-muted">Error</label>
                    <div className="mt-1 p-3 bg-acid-red/10 border border-acid-red/30 rounded font-theme-data text-sm text-acid-red">
                      {selectedJob.error}
                    </div>
                  </div>
                )}

                <div>
                  <label className="font-theme-data text-xs text-text-muted">Payload</label>
                  <pre className="mt-1 p-3 bg-surface rounded font-theme-data text-xs text-text overflow-x-auto">
                    {JSON.stringify(selectedJob.payload, null, 2)}
                  </pre>
                </div>

                {selectedJob.result && (
                  <div>
                    <label className="font-theme-data text-xs text-text-muted">Result</label>
                    <pre className="mt-1 p-3 bg-surface rounded font-theme-data text-xs text-text overflow-x-auto">
                      {JSON.stringify(selectedJob.result, null, 2)}
                    </pre>
                  </div>
                )}

                <div className="flex gap-3 pt-4 border-t border-[var(--accent)]/20">
                  {selectedJob.status === 'failed' && (
                    <button
                      onClick={() => {
                        handleRetryJob(selectedJob.id);
                        setSelectedJob(null);
                      }}
                      className="px-4 py-2 bg-[var(--acid-cyan)]/20 border border-[var(--acid-cyan)]/40 text-[var(--acid-cyan)] font-theme-data text-sm rounded hover:bg-[var(--acid-cyan)]/30"
                    >
                      Retry Job
                    </button>
                  )}
                  {(selectedJob.status === 'pending' || selectedJob.status === 'processing') && (
                    <button
                      onClick={() => {
                        handleCancelJob(selectedJob.id);
                        setSelectedJob(null);
                      }}
                      className="px-4 py-2 bg-acid-red/20 border border-acid-red/40 text-acid-red font-theme-data text-sm rounded hover:bg-acid-red/30"
                    >
                      Cancel Job
                    </button>
                  )}
                  <button
                    onClick={() => setSelectedJob(null)}
                    className="px-4 py-2 border border-[var(--accent)]/40 text-text-muted font-theme-data text-sm rounded hover:text-text"
                  >
                    Close
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </>
  );
}
