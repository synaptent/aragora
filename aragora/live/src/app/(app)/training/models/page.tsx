'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { ErrorWithRetry } from '@/components/ErrorWithRetry';
import { logger } from '@/utils/logger';

interface TrainingJob {
  id: string;
  vertical: string;
  status: 'pending' | 'training' | 'completed' | 'failed' | 'cancelled';
  base_model: string;
  adapter_name: string;
  created_at: string | null;
  training_data_examples: number;
}

interface JobMetrics {
  job_id: string;
  status: string;
  training_data_examples: number;
  training_data_debates: number;
  final_loss: number | null;
  elo_rating: number | null;
  win_rate: number | null;
  vertical_accuracy: number | null;
}

interface JobArtifacts {
  job_id: string;
  checkpoint_path: string | null;
  data_directory: string | null;
  files: Array<{ name: string; size_bytes: number; type: string }>;
}

type TabType = 'all' | 'pending' | 'training' | 'completed' | 'failed';

export default function ModelRegistryPage() {
  const { config } = useBackend();
  const backendUrl = config.api;

  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [selectedJob, setSelectedJob] = useState<TrainingJob | null>(null);
  const [jobMetrics, setJobMetrics] = useState<JobMetrics | null>(null);
  const [jobArtifacts, setJobArtifacts] = useState<JobArtifacts | null>(null);
  const [activeTab, setActiveTab] = useState<TabType>('all');
  const [loading, setLoading] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);

  const fetchJobs = useCallback(
    async (statusFilter?: string) => {
      setLoading(true);
      setError(null);

      try {
        const params = new URLSearchParams({ limit: '100' });
        if (statusFilter && statusFilter !== 'all') {
          params.set('status', statusFilter);
        }

        const response = await fetch(`${backendUrl}/api/training/jobs?${params}`);
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || `HTTP ${response.status}`);
        }

        const data = await response.json();
        setJobs(data.jobs || []);
        setTotal(data.total || 0);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch training jobs');
        setJobs([]);
      } finally {
        setLoading(false);
      }
    },
    [backendUrl],
  );

  const fetchJobDetails = useCallback(
    async (job: TrainingJob) => {
      setSelectedJob(job);
      setLoadingDetail(true);
      setJobMetrics(null);
      setJobArtifacts(null);

      try {
        const [metricsRes, artifactsRes] = await Promise.all([
          fetch(`${backendUrl}/api/training/jobs/${job.id}/metrics`),
          fetch(`${backendUrl}/api/training/jobs/${job.id}/artifacts`),
        ]);

        if (metricsRes.ok) {
          const metricsData = await metricsRes.json();
          setJobMetrics(metricsData);
        }

        if (artifactsRes.ok) {
          const artifactsData = await artifactsRes.json();
          setJobArtifacts(artifactsData);
        }
      } catch (err) {
        logger.error('Failed to fetch job details:', err);
      } finally {
        setLoadingDetail(false);
      }
    },
    [backendUrl],
  );

  const handleStartJob = async (jobId: string) => {
    setActionLoading(jobId);
    try {
      const response = await fetch(`${backendUrl}/api/training/jobs/${jobId}/start`, {
        method: 'POST',
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || 'Failed to start job');
      }

      // Refresh job list
      await fetchJobs(activeTab);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start training');
    } finally {
      setActionLoading(null);
    }
  };

  const handleCancelJob = async (jobId: string) => {
    if (!confirm('Are you sure you want to cancel this job?')) return;

    setActionLoading(jobId);
    try {
      const response = await fetch(`${backendUrl}/api/training/jobs/${jobId}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || 'Failed to cancel job');
      }

      // Refresh job list
      await fetchJobs(activeTab);
      if (selectedJob?.id === jobId) {
        setSelectedJob(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel job');
    } finally {
      setActionLoading(null);
    }
  };

  useEffect(() => {
    fetchJobs(activeTab);
  }, [fetchJobs, activeTab]);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'pending':
        return 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30';
      case 'training':
        return 'text-blue-400 bg-blue-500/10 border-blue-500/30';
      case 'completed':
        return 'text-green-400 bg-green-500/10 border-green-500/30';
      case 'failed':
        return 'text-red-400 bg-red-500/10 border-red-500/30';
      case 'cancelled':
        return 'text-text-muted bg-surface border-border';
      default:
        return 'text-text-muted bg-surface border-border';
    }
  };

  const getVerticalColor = (vertical: string) => {
    const colors: Record<string, string> = {
      finance: 'text-green-400',
      legal: 'text-blue-400',
      healthcare: 'text-red-400',
      technology: 'text-purple-400',
      education: 'text-yellow-400',
    };
    return colors[vertical.toLowerCase()] || 'text-text-muted';
  };

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const filteredJobs = activeTab === 'all' ? jobs : jobs.filter((j) => j.status === activeTab);

  return (
    <div className="min-h-screen bg-bg text-text relative overflow-hidden">
      <Scanlines />
      <CRTVignette />

      <div className="max-w-7xl mx-auto px-4 py-8 relative z-10">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <Link href="/" className="hover:opacity-80 transition-opacity">
            <AsciiBannerCompact />
          </Link>
          <div className="flex items-center gap-4">
            <Link
              href="/training/explorer"
              className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
            >
              [DATA EXPLORER]
            </Link>
            <ThemeToggle />
            <BackendSelector />
          </div>
        </div>

        {/* Title */}
        <div className="mb-8">
          <h1 className="text-3xl font-theme-data font-bold text-[var(--accent)] mb-2">
            Model Registry
          </h1>
          <p className="text-text-muted font-theme-data text-sm">
            Track fine-tuned specialist models and monitor training progress
          </p>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-6">
            <ErrorWithRetry error={error} onRetry={() => fetchJobs(activeTab)} />
          </div>
        )}

        {/* Status Tabs */}
        <div className="flex gap-2 mb-6 flex-wrap">
          {(['all', 'pending', 'training', 'completed', 'failed'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 font-theme-data text-sm rounded transition-colors ${
                activeTab === tab
                  ? 'bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]'
                  : 'bg-surface border border-border text-text-muted hover:text-text'
              }`}
            >
              {tab.toUpperCase()}
              {tab === 'all' && ` (${total})`}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Job List */}
          <div className="lg:col-span-2 space-y-4">
            {loading ? (
              <div className="p-8 text-center">
                <div className="text-[var(--accent)] font-theme-data animate-pulse">
                  Loading models...
                </div>
              </div>
            ) : filteredJobs.length === 0 ? (
              <div className="p-8 text-center bg-surface border border-border rounded-lg">
                <p className="text-text-muted font-theme-data">No training jobs found</p>
                <p className="text-xs text-text-muted font-theme-data mt-2">
                  Start training specialist models via the verticals page
                </p>
              </div>
            ) : (
              filteredJobs.map((job) => (
                <div
                  key={job.id}
                  onClick={() => fetchJobDetails(job)}
                  className={`p-4 bg-surface border rounded-lg cursor-pointer transition-all ${
                    selectedJob?.id === job.id
                      ? 'border-[var(--accent)]'
                      : 'border-border hover:border-[var(--accent)]/50'
                  }`}
                >
                  <div className="flex items-start justify-between gap-4 mb-3">
                    <div className="flex items-center gap-3">
                      <span
                        className={`px-2 py-1 text-xs font-theme-data rounded border ${getStatusColor(job.status)}`}
                      >
                        {job.status.toUpperCase()}
                      </span>
                      <span
                        className={`text-sm font-theme-data font-bold ${getVerticalColor(job.vertical)}`}
                      >
                        {job.vertical}
                      </span>
                    </div>
                    <div className="flex gap-2">
                      {job.status === 'pending' && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleStartJob(job.id);
                          }}
                          disabled={actionLoading === job.id}
                          className="px-3 py-1 text-xs font-theme-data bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] rounded hover:bg-[var(--accent)]/30 disabled:opacity-50 transition-colors"
                        >
                          {actionLoading === job.id ? '...' : 'START'}
                        </button>
                      )}
                      {(job.status === 'pending' || job.status === 'training') && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleCancelJob(job.id);
                          }}
                          disabled={actionLoading === job.id}
                          className="px-3 py-1 text-xs font-theme-data bg-red-500/20 border border-red-500/50 text-red-400 rounded hover:bg-red-500/30 disabled:opacity-50 transition-colors"
                        >
                          CANCEL
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-4 text-xs font-theme-data text-text-muted mb-2">
                    <span>
                      ID: <span className="text-text">{job.id.slice(0, 12)}...</span>
                    </span>
                    <span>
                      Base: <span className="text-text">{job.base_model}</span>
                    </span>
                  </div>

                  <div className="flex items-center gap-4 text-xs font-theme-data text-text-muted">
                    <span>
                      Examples:{' '}
                      <span className="text-[var(--acid-cyan)]">{job.training_data_examples}</span>
                    </span>
                    {job.adapter_name && (
                      <span>
                        Adapter: <span className="text-text">{job.adapter_name}</span>
                      </span>
                    )}
                    {job.created_at && (
                      <span>Created: {new Date(job.created_at).toLocaleDateString()}</span>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Detail Panel */}
          <div className="lg:col-span-1">
            {selectedJob ? (
              <div className="p-4 bg-surface border border-border rounded-lg space-y-4 sticky top-4">
                <div className="flex items-center justify-between">
                  <h3 className="font-theme-data font-bold text-[var(--accent)]">Model Details</h3>
                  <button
                    onClick={() => setSelectedJob(null)}
                    className="text-text-muted hover:text-text text-xs"
                  >
                    [X]
                  </button>
                </div>

                {loadingDetail ? (
                  <div className="py-4 text-center">
                    <div className="text-[var(--accent)] font-theme-data animate-pulse text-sm">
                      Loading...
                    </div>
                  </div>
                ) : (
                  <>
                    {/* Basic Info */}
                    <div className="p-3 bg-bg border border-border rounded">
                      <div className="text-xs font-theme-data text-text-muted uppercase mb-2">
                        Info
                      </div>
                      <div className="space-y-1 text-sm font-theme-data">
                        <div className="flex justify-between">
                          <span className="text-text-muted">Status</span>
                          <span className={getStatusColor(selectedJob.status).split(' ')[0]}>
                            {selectedJob.status}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-text-muted">Vertical</span>
                          <span className={getVerticalColor(selectedJob.vertical)}>
                            {selectedJob.vertical}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-text-muted">Base Model</span>
                          <span className="text-text">{selectedJob.base_model}</span>
                        </div>
                      </div>
                    </div>

                    {/* Metrics */}
                    {jobMetrics && (
                      <div className="p-3 bg-bg border border-border rounded">
                        <div className="text-xs font-theme-data text-text-muted uppercase mb-2">
                          Metrics
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          {jobMetrics.elo_rating !== null && (
                            <div className="p-2 bg-surface rounded">
                              <div className="text-xs text-text-muted">ELO</div>
                              <div className="text-lg font-theme-data text-[var(--accent)]">
                                {(Number(jobMetrics.elo_rating) || 0).toFixed(0)}
                              </div>
                            </div>
                          )}
                          {jobMetrics.win_rate !== null && (
                            <div className="p-2 bg-surface rounded">
                              <div className="text-xs text-text-muted">Win Rate</div>
                              <div className="text-lg font-theme-data text-[var(--acid-cyan)]">
                                {((Number(jobMetrics.win_rate) || 0) * 100).toFixed(1)}%
                              </div>
                            </div>
                          )}
                          {jobMetrics.vertical_accuracy !== null && (
                            <div className="p-2 bg-surface rounded">
                              <div className="text-xs text-text-muted">Accuracy</div>
                              <div className="text-lg font-theme-data text-yellow-400">
                                {((Number(jobMetrics.vertical_accuracy) || 0) * 100).toFixed(1)}%
                              </div>
                            </div>
                          )}
                          {jobMetrics.final_loss !== null && (
                            <div className="p-2 bg-surface rounded">
                              <div className="text-xs text-text-muted">Final Loss</div>
                              <div className="text-lg font-theme-data text-text">
                                {(Number(jobMetrics.final_loss) || 0).toFixed(4)}
                              </div>
                            </div>
                          )}
                        </div>
                        <div className="mt-2 text-xs font-theme-data text-text-muted">
                          Examples: {jobMetrics.training_data_examples} | Debates:{' '}
                          {jobMetrics.training_data_debates}
                        </div>
                      </div>
                    )}

                    {/* Artifacts */}
                    {jobArtifacts && (
                      <div className="p-3 bg-bg border border-border rounded">
                        <div className="text-xs font-theme-data text-text-muted uppercase mb-2">
                          Artifacts
                        </div>
                        {jobArtifacts.checkpoint_path ? (
                          <div className="text-xs font-theme-data mb-2">
                            <span className="text-text-muted">Checkpoint: </span>
                            <span className="text-[var(--accent)] break-all">
                              {jobArtifacts.checkpoint_path}
                            </span>
                          </div>
                        ) : (
                          <div className="text-xs font-theme-data text-text-muted mb-2">
                            No checkpoint available
                          </div>
                        )}
                        {jobArtifacts.files.length > 0 && (
                          <div className="space-y-1">
                            {jobArtifacts.files.map((file, i) => (
                              <div key={i} className="flex justify-between text-xs font-theme-data">
                                <span className="text-text truncate">{file.name}</span>
                                <span className="text-text-muted">
                                  {formatBytes(file.size_bytes)}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Actions */}
                    <div className="flex gap-2">
                      {selectedJob.status === 'pending' && (
                        <button
                          onClick={() => handleStartJob(selectedJob.id)}
                          disabled={actionLoading === selectedJob.id}
                          className="flex-1 px-4 py-2 font-theme-data text-sm bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] rounded hover:bg-[var(--accent)]/30 disabled:opacity-50 transition-colors"
                        >
                          {actionLoading === selectedJob.id ? 'STARTING...' : 'START TRAINING'}
                        </button>
                      )}
                      {selectedJob.status === 'completed' && (
                        <Link
                          href={`/verticals?vertical=${selectedJob.vertical}`}
                          className="flex-1 px-4 py-2 font-theme-data text-sm text-center bg-[var(--acid-cyan)]/20 border border-[var(--acid-cyan)] text-[var(--acid-cyan)] rounded hover:bg-[var(--acid-cyan)]/30 transition-colors"
                        >
                          VIEW VERTICAL
                        </Link>
                      )}
                    </div>
                  </>
                )}
              </div>
            ) : (
              <div className="p-8 bg-surface border border-border rounded-lg text-center">
                <p className="text-text-muted font-theme-data text-sm">
                  Select a model to view details
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Summary Stats */}
        {jobs.length > 0 && (
          <div className="mt-8 p-4 bg-surface border border-border rounded-lg">
            <h3 className="text-sm font-theme-data font-bold text-[var(--accent)] mb-4">
              Registry Summary
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <div className="p-3 bg-bg rounded text-center">
                <div className="text-2xl font-theme-data text-text">{jobs.length}</div>
                <div className="text-xs font-theme-data text-text-muted">Total Models</div>
              </div>
              <div className="p-3 bg-bg rounded text-center">
                <div className="text-2xl font-theme-data text-yellow-400">
                  {jobs.filter((j) => j.status === 'pending').length}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Pending</div>
              </div>
              <div className="p-3 bg-bg rounded text-center">
                <div className="text-2xl font-theme-data text-blue-400">
                  {jobs.filter((j) => j.status === 'training').length}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Training</div>
              </div>
              <div className="p-3 bg-bg rounded text-center">
                <div className="text-2xl font-theme-data text-green-400">
                  {jobs.filter((j) => j.status === 'completed').length}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Completed</div>
              </div>
              <div className="p-3 bg-bg rounded text-center">
                <div className="text-2xl font-theme-data text-red-400">
                  {jobs.filter((j) => j.status === 'failed').length}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Failed</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
