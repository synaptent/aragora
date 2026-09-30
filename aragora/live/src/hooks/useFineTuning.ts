'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { API_BASE_URL } from '@/config';

const API_BASE = API_BASE_URL;

// ============================================================================
// Types
// ============================================================================

export interface FineTuningJob {
  id: string;
  name: string;
  vertical: string;
  baseModel: string;
  status: 'queued' | 'preparing' | 'training' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  currentEpoch?: number;
  totalEpochs?: number;
  currentStep?: number;
  totalSteps?: number;
  loss?: number;
  trainingExamples: number;
  startedAt?: string;
  completedAt?: string;
  outputPath?: string;
  error?: string;
}

export interface TrainingParameters {
  jobName: string;
  datasetPath: string;
  loraR: number;
  loraAlpha: number;
  loraDropout: number;
  numEpochs: number;
  batchSize: number;
  learningRate: number;
  maxSeqLength: number;
  quantization: '4bit' | '8bit' | 'none';
  gradientCheckpointing: boolean;
}

export interface AvailableModel {
  id: string;
  name: string;
  provider: string;
  size: string;
  vertical: string;
  capabilities: string[];
  recommended?: boolean;
}

export interface CreateJobData {
  name: string;
  vertical: string;
  base_model: string;
  training_config: {
    lora_r: number;
    lora_alpha: number;
    lora_dropout: number;
    num_epochs: number;
    batch_size: number;
    learning_rate: number;
    max_seq_length: number;
    quantization: string;
    gradient_checkpointing: boolean;
    dataset_path?: string;
  };
}

export interface JobMetrics {
  job_id: string;
  status: string;
  training_data_examples: number;
  training_data_debates: number;
  final_loss?: number;
  elo_rating?: number;
  win_rate?: number;
  vertical_accuracy?: Record<string, number>;
}

export interface JobArtifacts {
  job_id: string;
  checkpoint_path?: string;
  data_directory?: string;
  files: Array<{ name: string; size_bytes: number; type: string }>;
}

export interface TrainingStats {
  available_exporters: string[];
  export_directory: string;
  exported_files: Array<{
    name: string;
    size_bytes: number;
    created_at: string;
    modified_at: string;
  }>;
  sft_available?: boolean;
}

export interface TrainingFormats {
  formats: Record<
    string,
    { description: string; schema: Record<string, unknown>; use_case: string }
  >;
  output_formats: string[];
  endpoints: Record<string, string>;
}

interface UseFineTuningState {
  jobs: FineTuningJob[];
  loading: boolean;
  error: string | null;
}

// ============================================================================
// Hook
// ============================================================================

export interface UseFineTuningOptions {
  /** Auto-load jobs on mount */
  autoLoad?: boolean;
  /** Filter by vertical */
  vertical?: string;
  /** Filter by status */
  status?: string;
  /** Polling interval in ms (0 to disable) */
  pollInterval?: number;
}

export interface UseFineTuningReturn extends UseFineTuningState {
  // Load methods
  loadJobs: (options?: { vertical?: string; status?: string }) => Promise<void>;
  loadJob: (id: string) => Promise<FineTuningJob | null>;
  refetch: () => Promise<void>;

  // Job CRUD
  createJob: (data: CreateJobData) => Promise<FineTuningJob | null>;
  startJob: (id: string) => Promise<boolean>;
  cancelJob: (id: string) => Promise<boolean>;

  // Metrics and artifacts
  getJobMetrics: (id: string) => Promise<JobMetrics | null>;
  getJobArtifacts: (id: string) => Promise<JobArtifacts | null>;

  // Export endpoints
  exportSFT: (options?: { minConfidence?: number; limit?: number }) => Promise<unknown[] | null>;
  exportDPO: (options?: {
    minConfidenceDiff?: number;
    limit?: number;
  }) => Promise<unknown[] | null>;

  // Stats and formats
  getStats: () => Promise<TrainingStats | null>;
  getFormats: () => Promise<TrainingFormats | null>;

  // Computed stats
  stats: { running: number; queued: number; completed: number; failed: number };
}

/**
 * Hook for managing fine-tuning jobs and training data.
 *
 * @example
 * ```tsx
 * const {
 *   jobs,
 *   stats,
 *   loading,
 *   createJob,
 *   startJob,
 *   cancelJob,
 * } = useFineTuning({ autoLoad: true });
 *
 * // Create a new training job
 * const job = await createJob({
 *   name: 'legal_specialist_v1',
 *   vertical: 'legal',
 *   base_model: 'nlpaueb/legal-bert-base-uncased',
 *   training_config: { ... },
 * });
 *
 * // Start training
 * await startJob(job.id);
 * ```
 */
export function useFineTuning(options: UseFineTuningOptions = {}): UseFineTuningReturn {
  const { autoLoad = true, vertical, status, pollInterval = 0 } = options;

  const [state, setState] = useState<UseFineTuningState>({ jobs: [], loading: true, error: null });

  // =========================================================================
  // Load methods
  // =========================================================================

  const loadJobs = useCallback(
    async (opts?: { vertical?: string; status?: string }) => {
      setState((s) => ({ ...s, loading: true, error: null }));

      try {
        const params = new URLSearchParams();
        const filterVertical = opts?.vertical || vertical;
        const filterStatus = opts?.status || status;

        if (filterVertical) params.set('vertical', filterVertical);
        if (filterStatus) params.set('status', filterStatus);

        const query = params.toString();
        const url = `${API_BASE}/api/training/jobs${query ? `?${query}` : ''}`;

        const response = await fetch(url);
        if (!response.ok) {
          if (response.status === 503) {
            throw new Error('Training pipeline not available');
          }
          throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        const jobs = (data.jobs || []).map(mapBackendJob);

        setState((s) => ({ ...s, jobs, loading: false }));
      } catch (e) {
        setState((s) => ({
          ...s,
          loading: false,
          error: e instanceof Error ? e.message : 'Failed to load jobs',
        }));
      }
    },
    [vertical, status],
  );

  const loadJob = useCallback(async (id: string): Promise<FineTuningJob | null> => {
    try {
      const response = await fetch(`${API_BASE}/api/training/jobs/${id}`);
      if (!response.ok) {
        if (response.status === 404) return null;
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      return mapBackendJob(data);
    } catch (e) {
      setState((s) => ({ ...s, error: e instanceof Error ? e.message : 'Failed to load job' }));
      return null;
    }
  }, []);

  const refetch = useCallback(async () => {
    await loadJobs();
  }, [loadJobs]);

  // =========================================================================
  // Job CRUD
  // =========================================================================

  const createJob = useCallback(async (data: CreateJobData): Promise<FineTuningJob | null> => {
    try {
      const response = await fetch(`${API_BASE}/api/training/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${response.status}`);
      }

      const result = await response.json();
      const job = mapBackendJob(result.job || result);

      // Update local state
      setState((s) => ({ ...s, jobs: [...s.jobs, job] }));

      return job;
    } catch (e) {
      setState((s) => ({ ...s, error: e instanceof Error ? e.message : 'Failed to create job' }));
      return null;
    }
  }, []);

  const startJob = useCallback(async (id: string): Promise<boolean> => {
    try {
      const response = await fetch(`${API_BASE}/api/training/jobs/${id}/start`, { method: 'POST' });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${response.status}`);
      }

      // Update local state
      setState((s) => ({
        ...s,
        jobs: s.jobs.map((j) =>
          j.id === id
            ? { ...j, status: 'training' as const, startedAt: new Date().toISOString() }
            : j,
        ),
      }));

      return true;
    } catch (e) {
      setState((s) => ({ ...s, error: e instanceof Error ? e.message : 'Failed to start job' }));
      return false;
    }
  }, []);

  const cancelJob = useCallback(async (id: string): Promise<boolean> => {
    try {
      const response = await fetch(`${API_BASE}/api/training/jobs/${id}`, { method: 'DELETE' });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${response.status}`);
      }

      // Update local state
      setState((s) => ({
        ...s,
        jobs: s.jobs.map((j) => (j.id === id ? { ...j, status: 'cancelled' as const } : j)),
      }));

      return true;
    } catch (e) {
      setState((s) => ({ ...s, error: e instanceof Error ? e.message : 'Failed to cancel job' }));
      return false;
    }
  }, []);

  // =========================================================================
  // Metrics and artifacts
  // =========================================================================

  const getJobMetrics = useCallback(async (id: string): Promise<JobMetrics | null> => {
    try {
      const response = await fetch(`${API_BASE}/api/training/jobs/${id}/metrics`);
      if (!response.ok) {
        if (response.status === 404) return null;
        throw new Error(`HTTP ${response.status}`);
      }
      return await response.json();
    } catch (e) {
      setState((s) => ({ ...s, error: e instanceof Error ? e.message : 'Failed to get metrics' }));
      return null;
    }
  }, []);

  const getJobArtifacts = useCallback(async (id: string): Promise<JobArtifacts | null> => {
    try {
      const response = await fetch(`${API_BASE}/api/training/jobs/${id}/artifacts`);
      if (!response.ok) {
        if (response.status === 404) return null;
        throw new Error(`HTTP ${response.status}`);
      }
      return await response.json();
    } catch (e) {
      setState((s) => ({
        ...s,
        error: e instanceof Error ? e.message : 'Failed to get artifacts',
      }));
      return null;
    }
  }, []);

  // =========================================================================
  // Export endpoints
  // =========================================================================

  const exportSFT = useCallback(
    async (opts?: { minConfidence?: number; limit?: number }): Promise<unknown[] | null> => {
      try {
        const params = new URLSearchParams();
        if (opts?.minConfidence) params.set('min_confidence', String(opts.minConfidence));
        if (opts?.limit) params.set('limit', String(opts.limit));

        const query = params.toString();
        const url = `${API_BASE}/api/training/export/sft${query ? `?${query}` : ''}`;

        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        return data.records || [];
      } catch (e) {
        setState((s) => ({
          ...s,
          error: e instanceof Error ? e.message : 'Failed to export SFT data',
        }));
        return null;
      }
    },
    [],
  );

  const exportDPO = useCallback(
    async (opts?: { minConfidenceDiff?: number; limit?: number }): Promise<unknown[] | null> => {
      try {
        const params = new URLSearchParams();
        if (opts?.minConfidenceDiff)
          params.set('min_confidence_diff', String(opts.minConfidenceDiff));
        if (opts?.limit) params.set('limit', String(opts.limit));

        const query = params.toString();
        const url = `${API_BASE}/api/training/export/dpo${query ? `?${query}` : ''}`;

        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        return data.records || [];
      } catch (e) {
        setState((s) => ({
          ...s,
          error: e instanceof Error ? e.message : 'Failed to export DPO data',
        }));
        return null;
      }
    },
    [],
  );

  // =========================================================================
  // Stats and formats
  // =========================================================================

  const getStats = useCallback(async (): Promise<TrainingStats | null> => {
    try {
      const response = await fetch(`${API_BASE}/api/training/stats`);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return await response.json();
    } catch (e) {
      setState((s) => ({ ...s, error: e instanceof Error ? e.message : 'Failed to get stats' }));
      return null;
    }
  }, []);

  const getFormats = useCallback(async (): Promise<TrainingFormats | null> => {
    try {
      const response = await fetch(`${API_BASE}/api/training/formats`);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return await response.json();
    } catch (e) {
      setState((s) => ({ ...s, error: e instanceof Error ? e.message : 'Failed to get formats' }));
      return null;
    }
  }, []);

  // =========================================================================
  // Computed stats
  // =========================================================================

  const stats = useMemo(
    () => ({
      running: state.jobs.filter((j) => j.status === 'training' || j.status === 'preparing').length,
      queued: state.jobs.filter((j) => j.status === 'queued').length,
      completed: state.jobs.filter((j) => j.status === 'completed').length,
      failed: state.jobs.filter((j) => j.status === 'failed').length,
    }),
    [state.jobs],
  );

  // =========================================================================
  // Auto-load and polling
  // =========================================================================

  useEffect(() => {
    if (autoLoad) {
      loadJobs();
    }
  }, [autoLoad, loadJobs]);

  useEffect(() => {
    if (pollInterval > 0) {
      const interval = setInterval(() => {
        loadJobs();
      }, pollInterval);
      return () => clearInterval(interval);
    }
  }, [pollInterval, loadJobs]);

  return {
    ...state,
    stats,
    loadJobs,
    loadJob,
    refetch,
    createJob,
    startJob,
    cancelJob,
    getJobMetrics,
    getJobArtifacts,
    exportSFT,
    exportDPO,
    getStats,
    getFormats,
  };
}

// ============================================================================
// Helpers
// ============================================================================

/**
 * Map backend job response to frontend FineTuningJob type.
 */
function mapBackendJob(data: Record<string, unknown>): FineTuningJob {
  // Backend job structure from training handler:
  // { id, vertical, status, base_model, adapter_name, created_at, training_data_examples }

  // Map status from backend format
  const backendStatus = (data.status as string) || 'queued';
  const statusMap: Record<string, FineTuningJob['status']> = {
    pending: 'queued',
    ready: 'queued',
    training: 'training',
    completed: 'completed',
    failed: 'failed',
    cancelled: 'cancelled',
  };
  const status = statusMap[backendStatus] || 'queued';

  // Calculate progress from metrics if available
  let progress = 0;
  if (status === 'completed') {
    progress = 1;
  } else if (status === 'training') {
    // Estimate from current/total steps or epochs if available
    const currentStep = (data.current_step as number) || 0;
    const totalSteps = (data.total_steps as number) || 1;
    progress = totalSteps > 0 ? currentStep / totalSteps : 0.5;
  }

  return {
    id: (data.id as string) || '',
    name: (data.adapter_name as string) || (data.name as string) || '',
    vertical: (data.vertical as string) || '',
    baseModel: (data.base_model as string) || '',
    status,
    progress,
    currentEpoch: (data.current_epoch as number) || undefined,
    totalEpochs: (data.total_epochs as number) || undefined,
    currentStep: (data.current_step as number) || undefined,
    totalSteps: (data.total_steps as number) || undefined,
    loss: (data.final_loss as number) || (data.loss as number) || undefined,
    trainingExamples: (data.training_data_examples as number) || 0,
    startedAt: (data.started_at as string) || (data.created_at as string) || undefined,
    completedAt: (data.completed_at as string) || undefined,
    outputPath: (data.checkpoint_path as string) || (data.output_path as string) || undefined,
    error: (data.error as string) || undefined,
  };
}

export default useFineTuning;
