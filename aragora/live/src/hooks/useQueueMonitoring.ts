/**
 * Hook for queue monitoring
 *
 * Provides methods to:
 * - Fetch queue statistics
 * - List jobs with filtering
 * - Retry failed jobs
 * - Cancel pending jobs
 * - Get worker status
 */

import { useState, useCallback, useEffect } from 'react';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';
import type { QueueStats, QueueJob, QueueWorker } from '../components/queue';

const API_BASE = API_BASE_URL;

interface UseQueueMonitoringOptions {
  autoRefresh?: boolean;
  refreshInterval?: number;
}

interface UseQueueMonitoringResult {
  stats: QueueStats | null;
  jobs: QueueJob[];
  workers: QueueWorker[];
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  retryJob: (jobId: string) => Promise<void>;
  cancelJob: (jobId: string) => Promise<void>;
  submitJob: (payload: SubmitJobPayload) => Promise<string>;
  setStatusFilter: (status: string | null) => void;
}

export interface SubmitJobPayload {
  question: string;
  agents?: string[];
  rounds?: number;
  consensus?: string;
  priority?: number;
  metadata?: Record<string, unknown>;
}

export function useQueueMonitoring(
  options: UseQueueMonitoringOptions = {},
): UseQueueMonitoringResult {
  const { autoRefresh = false, refreshInterval = 5000 } = options;

  const [stats, setStats] = useState<QueueStats | null>(null);
  const [jobs, setJobs] = useState<QueueJob[]>([]);
  const [workers, setWorkers] = useState<QueueWorker[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);

  // Fetch queue statistics
  const fetchStats = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/queue/stats`);
      if (!response.ok) {
        throw new Error(`Failed to fetch stats: ${response.status}`);
      }
      const data = await response.json();
      setStats(data.stats);
    } catch (err) {
      logger.error('Failed to fetch queue stats:', err);
      // Don't set error for stats - may not be available
    }
  }, []);

  // Fetch jobs list
  const fetchJobs = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (statusFilter) {
        params.set('status', statusFilter);
      }
      const response = await fetch(`${API_BASE}/api/queue/jobs?${params}`);
      if (!response.ok) {
        throw new Error(`Failed to fetch jobs: ${response.status}`);
      }
      const data = await response.json();
      setJobs(
        data.jobs.map((job: Record<string, unknown>) => ({
          id: job.job_id as string,
          status: job.status as string,
          createdAt: job.created_at as string,
          startedAt: job.started_at as string | undefined,
          completedAt: job.completed_at as string | undefined,
          attempts: job.attempts as number,
          maxAttempts: job.max_attempts as number,
          priority: job.priority as number,
          error: job.error as string | undefined,
          workerId: job.worker_id as string | undefined,
          metadata: job.metadata as Record<string, unknown>,
        })),
      );
    } catch (err) {
      logger.error('Failed to fetch jobs:', err);
    }
  }, [statusFilter]);

  // Fetch workers list
  const fetchWorkers = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/queue/workers`);
      if (!response.ok) {
        throw new Error(`Failed to fetch workers: ${response.status}`);
      }
      const data = await response.json();
      setWorkers(
        data.workers.map((worker: Record<string, unknown>) => ({
          workerId: worker.worker_id as string,
          group: worker.group as string,
          pending: worker.pending as number,
          idleMs: worker.idle_ms as number,
        })),
      );
    } catch (err) {
      logger.error('Failed to fetch workers:', err);
    }
  }, []);

  // Refresh all data
  const refresh = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      await Promise.all([fetchStats(), fetchJobs(), fetchWorkers()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setIsLoading(false);
    }
  }, [fetchStats, fetchJobs, fetchWorkers]);

  // Retry a failed job
  const retryJob = useCallback(
    async (jobId: string) => {
      const response = await fetch(`${API_BASE}/api/queue/jobs/${jobId}/retry`, { method: 'POST' });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to retry job');
      }
      // Refresh after retry
      await refresh();
    },
    [refresh],
  );

  // Cancel a pending job
  const cancelJob = useCallback(
    async (jobId: string) => {
      const response = await fetch(`${API_BASE}/api/queue/jobs/${jobId}`, { method: 'DELETE' });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to cancel job');
      }
      // Refresh after cancel
      await refresh();
    },
    [refresh],
  );

  // Submit a new job
  const submitJob = useCallback(
    async (payload: SubmitJobPayload): Promise<string> => {
      const response = await fetch(`${API_BASE}/api/queue/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to submit job');
      }
      const data = await response.json();
      // Refresh after submit
      await refresh();
      return data.job_id;
    },
    [refresh],
  );

  // Initial fetch
  useEffect(() => {
    refresh();
  }, [refresh]);

  // Auto-refresh
  useEffect(() => {
    if (!autoRefresh) return;

    const interval = setInterval(() => {
      refresh();
    }, refreshInterval);

    return () => clearInterval(interval);
  }, [autoRefresh, refreshInterval, refresh]);

  return {
    stats,
    jobs,
    workers,
    isLoading,
    error,
    refresh,
    retryJob,
    cancelJob,
    submitJob,
    setStatusFilter,
  };
}
