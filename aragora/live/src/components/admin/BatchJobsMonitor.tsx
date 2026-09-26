'use client';

import { useState, useEffect, useCallback } from 'react';

interface BatchJob {
  id: string;
  user_id: string;
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';
  total_debates: number;
  processed_count: number;
  success_count: number;
  failure_count: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

interface BatchResult {
  id: string;
  job_id: string;
  debate_id: string;
  status: 'pending' | 'success' | 'error';
  processing_time_ms: number | null;
  error_message: string | null;
}

interface BatchJobsMonitorProps {
  apiBase?: string;
}

const STATUS_COLORS: Record<string, string> = {
  pending: 'text-gray-400 border-gray-400/30 bg-gray-400/10',
  processing: 'text-[var(--acid-cyan)] border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/10',
  completed: 'text-[var(--accent)] border-[var(--accent)]/30 bg-[var(--accent)]/10',
  failed: 'text-[var(--crimson)] border-[var(--crimson)]/30 bg-[var(--crimson)]/10',
  cancelled: 'text-orange-400 border-orange-400/30 bg-orange-400/10',
};

const RESULT_STATUS_COLORS: Record<string, string> = {
  pending: 'text-gray-400',
  success: 'text-[var(--accent)]',
  error: 'text-[var(--crimson)]',
};

export function BatchJobsMonitor({ apiBase = '/api' }: BatchJobsMonitorProps) {
  const [jobs, setJobs] = useState<BatchJob[]>([]);
  const [results, setResults] = useState<BatchResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<BatchJob | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [autoRefresh, setAutoRefresh] = useState(false);

  const fetchJobs = useCallback(async () => {
    try {
      const params = new URLSearchParams({ limit: '50' });
      if (statusFilter !== 'all') {
        params.set('status', statusFilter);
      }
      const response = await fetch(`${apiBase}/explainability/batch?${params}`);
      if (!response.ok) throw new Error('Failed to fetch batch jobs');
      const data = await response.json();
      setJobs(data.jobs || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  }, [apiBase, statusFilter]);

  const fetchResults = useCallback(
    async (jobId: string) => {
      try {
        const response = await fetch(`${apiBase}/explainability/batch/${jobId}/results`);
        if (!response.ok) throw new Error('Failed to fetch job results');
        const data = await response.json();
        setResults(data.results || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      }
    },
    [apiBase],
  );

  const cancelJob = async (jobId: string) => {
    try {
      const response = await fetch(`${apiBase}/explainability/batch/${jobId}/cancel`, {
        method: 'POST',
      });
      if (!response.ok) throw new Error('Failed to cancel job');
      fetchJobs();
    } catch (err) {
      alert(`Error: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  useEffect(() => {
    setLoading(true);
    fetchJobs().finally(() => setLoading(false));
  }, [fetchJobs]);

  useEffect(() => {
    if (selectedJob) {
      fetchResults(selectedJob.id);
    }
  }, [selectedJob, fetchResults]);

  useEffect(() => {
    if (autoRefresh) {
      const interval = setInterval(fetchJobs, 5000);
      return () => clearInterval(interval);
    }
  }, [autoRefresh, fetchJobs]);

  const getProgressPercent = (job: BatchJob): number => {
    if (job.total_debates === 0) return 100;
    return Math.round((job.processed_count / job.total_debates) * 100);
  };

  const getElapsedTime = (job: BatchJob): string => {
    if (!job.started_at) return '-';
    const start = new Date(job.started_at).getTime();
    const end = job.completed_at ? new Date(job.completed_at).getTime() : Date.now();
    const seconds = Math.round((end - start) / 1000);
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}m ${remainingSeconds}s`;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="animate-pulse text-[var(--acid-cyan)]">Loading batch jobs...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 rounded-lg text-[var(--crimson)]">
        Error: {error}
      </div>
    );
  }

  const activeJobs = jobs.filter((j) => j.status === 'processing').length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-white">Batch Explainability Jobs</h2>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-gray-400">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded border-white/20 bg-black/50"
            />
            Auto-refresh
          </label>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-black/50 border border-white/20 rounded px-2 py-1 text-sm text-white"
          >
            <option value="all">All Status</option>
            <option value="pending">Pending</option>
            <option value="processing">Processing</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
          </select>
          <button
            onClick={() => fetchJobs()}
            className="px-3 py-1.5 bg-[var(--acid-cyan)]/10 border border-[var(--acid-cyan)]/30 rounded text-[var(--acid-cyan)] text-sm hover:bg-[var(--acid-cyan)]/20"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Stats Bar */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-black/50 border border-white/10 rounded-lg p-4">
          <div className="text-sm text-gray-400">Total Jobs</div>
          <div className="text-2xl font-semibold text-white">{jobs.length}</div>
        </div>
        <div className="bg-black/50 border border-[var(--acid-cyan)]/30 rounded-lg p-4">
          <div className="text-sm text-gray-400">Active</div>
          <div className="text-2xl font-semibold text-[var(--acid-cyan)]">{activeJobs}</div>
        </div>
        <div className="bg-black/50 border border-[var(--accent)]/30 rounded-lg p-4">
          <div className="text-sm text-gray-400">Completed</div>
          <div className="text-2xl font-semibold text-[var(--accent)]">
            {jobs.filter((j) => j.status === 'completed').length}
          </div>
        </div>
        <div className="bg-black/50 border border-[var(--crimson)]/30 rounded-lg p-4">
          <div className="text-sm text-gray-400">Failed</div>
          <div className="text-2xl font-semibold text-[var(--crimson)]">
            {jobs.filter((j) => j.status === 'failed').length}
          </div>
        </div>
      </div>

      {/* Jobs List */}
      <div className="bg-black/50 border border-white/10 rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-white/5">
            <tr>
              <th className="px-4 py-3 text-left text-sm text-gray-400">Job ID</th>
              <th className="px-4 py-3 text-left text-sm text-gray-400">Status</th>
              <th className="px-4 py-3 text-left text-sm text-gray-400">Progress</th>
              <th className="px-4 py-3 text-left text-sm text-gray-400">Success/Failed</th>
              <th className="px-4 py-3 text-left text-sm text-gray-400">Duration</th>
              <th className="px-4 py-3 text-left text-sm text-gray-400">Created</th>
              <th className="px-4 py-3 text-right text-sm text-gray-400">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {jobs.map((job) => (
              <tr
                key={job.id}
                className={`hover:bg-white/5 cursor-pointer ${
                  selectedJob?.id === job.id ? 'bg-[var(--acid-cyan)]/10' : ''
                }`}
                onClick={() => setSelectedJob(job)}
              >
                <td className="px-4 py-3">
                  <span className="font-theme-data text-sm text-white">
                    {job.id.substring(0, 12)}...
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded text-xs ${STATUS_COLORS[job.status]}`}>
                    {job.status}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 bg-white/10 rounded-full overflow-hidden">
                      <div
                        className={`h-full transition-all ${
                          job.status === 'failed' ? 'bg-[var(--crimson)]' : 'bg-[var(--acid-cyan)]'
                        }`}
                        style={{ width: `${getProgressPercent(job)}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-400 w-12 text-right">
                      {job.processed_count}/{job.total_debates}
                    </span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className="text-[var(--accent)] text-sm">{job.success_count}</span>
                  <span className="text-gray-500 mx-1">/</span>
                  <span className="text-[var(--crimson)] text-sm">{job.failure_count}</span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-400">{getElapsedTime(job)}</td>
                <td className="px-4 py-3 text-sm text-gray-400">
                  {new Date(job.created_at).toLocaleString()}
                </td>
                <td className="px-4 py-3 text-right">
                  {job.status === 'processing' && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        cancelJob(job.id);
                      }}
                      className="px-2 py-1 text-xs bg-[var(--crimson)]/10 text-[var(--crimson)] rounded hover:bg-[var(--crimson)]/20"
                    >
                      Cancel
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {jobs.length === 0 && (
          <div className="text-center py-8 text-gray-500">No batch jobs found</div>
        )}
      </div>

      {/* Job Results Panel */}
      {selectedJob && (
        <div className="bg-black/50 border border-white/10 rounded-lg p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium text-white">
              Job Results: {selectedJob.id.substring(0, 12)}...
            </h3>
            <button onClick={() => setSelectedJob(null)} className="text-gray-400 hover:text-white">
              Close
            </button>
          </div>

          {selectedJob.error_message && (
            <div className="mb-4 p-3 bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 rounded text-[var(--crimson)] text-sm">
              Error: {selectedJob.error_message}
            </div>
          )}

          <div className="space-y-2 max-h-64 overflow-y-auto">
            {results.length === 0 ? (
              <div className="text-center py-8 text-gray-500">No results yet</div>
            ) : (
              results.map((result) => (
                <div
                  key={result.id}
                  className="flex items-center justify-between p-3 bg-white/5 rounded"
                >
                  <div className="flex items-center gap-4">
                    <span className={`text-sm ${RESULT_STATUS_COLORS[result.status]}`}>
                      {result.status === 'success' ? '✓' : result.status === 'error' ? '✗' : '○'}
                    </span>
                    <span className="font-theme-data text-sm text-white">{result.debate_id}</span>
                    {result.processing_time_ms && (
                      <span className="text-xs text-gray-400">
                        {result.processing_time_ms.toFixed(0)}ms
                      </span>
                    )}
                  </div>
                  {result.error_message && (
                    <span className="text-xs text-[var(--crimson)] truncate max-w-xs">
                      {result.error_message}
                    </span>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
