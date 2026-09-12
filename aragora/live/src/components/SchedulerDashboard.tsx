'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '@/config';

// Types matching backend models
type TriggerType = 'cron' | 'webhook' | 'git_push' | 'file_upload' | 'manual' | 'interval';
type ScheduleStatus = 'active' | 'paused' | 'disabled' | 'running' | 'error';

interface ScheduledJob {
  job_id: string;
  schedule_id: string;
  name: string;
  status: ScheduleStatus;
  trigger_type: TriggerType;
  next_run: string | null;
  last_run: string | null;
  run_count: number;
  error_count: number;
}

interface JobRun {
  run_id: string;
  job_id: string;
  started_at: string;
  completed_at: string | null;
  status: string;
  session_id: string | null;
  findings_count: number;
  error_message: string | null;
  duration_ms: number;
}

interface SchedulerStatus {
  running: boolean;
  total_jobs: number;
  active_jobs: number;
  running_jobs: number;
}

interface SchedulerDashboardProps {
  apiBase: string;
}

const TRIGGER_TYPE_LABELS: Record<TriggerType, string> = {
  cron: 'Scheduled (Cron)',
  interval: 'Interval',
  webhook: 'Webhook',
  git_push: 'Git Push',
  file_upload: 'File Upload',
  manual: 'Manual Only',
};

const STATUS_STYLES: Record<ScheduleStatus, { bg: string; text: string; dot: string }> = {
  active: { bg: 'bg-[var(--accent)]/10', text: 'text-[var(--accent)]', dot: 'bg-[var(--accent)]' },
  running: {
    bg: 'bg-[var(--acid-cyan)]/10',
    text: 'text-[var(--acid-cyan)]',
    dot: 'bg-[var(--acid-cyan)] animate-pulse',
  },
  paused: { bg: 'bg-yellow-500/10', text: 'text-yellow-500', dot: 'bg-yellow-500' },
  disabled: { bg: 'bg-gray-500/10', text: 'text-gray-500', dot: 'bg-gray-500' },
  error: { bg: 'bg-red-500/10', text: 'text-red-400', dot: 'bg-red-500' },
};

export function SchedulerDashboard({ apiBase: _apiBase }: SchedulerDashboardProps) {
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [status, setStatus] = useState<SchedulerStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'jobs' | 'create' | 'history'>('jobs');
  const [selectedJob, setSelectedJob] = useState<ScheduledJob | null>(null);
  const [jobHistory, setJobHistory] = useState<JobRun[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // Form state for job creation
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    trigger_type: 'cron' as TriggerType,
    cron: '0 2 * * *',
    interval_minutes: 60,
    preset: '',
    audit_types: [] as string[],
    workspace_id: '',
    notify_on_complete: true,
    notify_on_findings: true,
    finding_severity_threshold: 'medium',
    tags: '',
  });
  const [createLoading, setCreateLoading] = useState(false);

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    setError(null);
    const { data, error: fetchError } = await apiFetch<{ jobs: ScheduledJob[]; count: number }>(
      '/api/scheduler/jobs',
    );
    if (fetchError) {
      setError(fetchError);
    } else if (data) {
      setJobs(data.jobs);
    }
    setLoading(false);
  }, []);

  const fetchStatus = useCallback(async () => {
    const { data } = await apiFetch<SchedulerStatus>('/api/scheduler/status');
    if (data) {
      setStatus(data);
    }
  }, []);

  const fetchJobHistory = useCallback(async (jobId: string) => {
    setHistoryLoading(true);
    const { data, error: histError } = await apiFetch<{ runs: JobRun[] }>(
      `/api/scheduler/jobs/${jobId}/history?limit=20`,
    );
    if (histError) {
      setError(histError);
    } else if (data) {
      setJobHistory(data.runs);
    }
    setHistoryLoading(false);
  }, []);

  useEffect(() => {
    fetchJobs();
    fetchStatus();
    const interval = setInterval(() => {
      fetchJobs();
      fetchStatus();
    }, 30000);
    return () => clearInterval(interval);
  }, [fetchJobs, fetchStatus]);

  useEffect(() => {
    if (selectedJob) {
      fetchJobHistory(selectedJob.job_id);
    }
  }, [selectedJob, fetchJobHistory]);

  const handleTrigger = async (jobId: string) => {
    const { error: triggerError } = await apiFetch(`/api/scheduler/jobs/${jobId}/trigger`, {
      method: 'POST',
    });
    if (triggerError) {
      setError(triggerError);
    } else {
      await fetchJobs();
    }
  };

  const handlePause = async (jobId: string) => {
    const { error: pauseError } = await apiFetch(`/api/scheduler/jobs/${jobId}/pause`, {
      method: 'POST',
    });
    if (pauseError) {
      setError(pauseError);
    } else {
      await fetchJobs();
    }
  };

  const handleResume = async (jobId: string) => {
    const { error: resumeError } = await apiFetch(`/api/scheduler/jobs/${jobId}/resume`, {
      method: 'POST',
    });
    if (resumeError) {
      setError(resumeError);
    } else {
      await fetchJobs();
    }
  };

  const handleDelete = async (jobId: string) => {
    if (!confirm('Are you sure you want to delete this job?')) return;
    const { error: deleteError } = await apiFetch(`/api/scheduler/jobs/${jobId}`, {
      method: 'DELETE',
    });
    if (deleteError) {
      setError(deleteError);
    } else {
      setSelectedJob(null);
      await fetchJobs();
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateLoading(true);
    setError(null);

    const payload = {
      name: formData.name,
      description: formData.description,
      trigger_type: formData.trigger_type,
      cron: formData.trigger_type === 'cron' ? formData.cron : undefined,
      interval_minutes:
        formData.trigger_type === 'interval' ? formData.interval_minutes : undefined,
      preset: formData.preset || undefined,
      audit_types: formData.audit_types.length > 0 ? formData.audit_types : undefined,
      workspace_id: formData.workspace_id || undefined,
      notify_on_complete: formData.notify_on_complete,
      notify_on_findings: formData.notify_on_findings,
      finding_severity_threshold: formData.finding_severity_threshold,
      tags: formData.tags ? formData.tags.split(',').map((t) => t.trim()) : [],
    };

    const { error: createError } = await apiFetch('/api/scheduler/jobs', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    if (createError) {
      setError(createError);
    } else {
      setFormData({
        name: '',
        description: '',
        trigger_type: 'cron',
        cron: '0 2 * * *',
        interval_minutes: 60,
        preset: '',
        audit_types: [],
        workspace_id: '',
        notify_on_complete: true,
        notify_on_findings: true,
        finding_severity_threshold: 'medium',
        tags: '',
      });
      setActiveTab('jobs');
      await fetchJobs();
    }
    setCreateLoading(false);
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleString();
  };

  const formatDuration = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  };

  if (loading && jobs.length === 0) {
    return (
      <div className="card p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-6 bg-surface rounded w-1/4" />
          <div className="h-32 bg-surface rounded" />
          <div className="h-32 bg-surface rounded" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Error display */}
      {error && (
        <div className="p-4 border border-red-500/30 bg-red-500/10 rounded text-red-400 text-sm font-theme-data">
          {error}
          <button onClick={() => setError(null)} className="ml-4 text-red-500 hover:text-red-400">
            [DISMISS]
          </button>
        </div>
      )}

      {/* Status bar */}
      {status && (
        <div className="flex gap-4 p-3 bg-surface border border-[var(--accent)]/20 rounded">
          <StatusBadge
            label="Scheduler"
            value={status.running ? 'RUNNING' : 'STOPPED'}
            active={status.running}
          />
          <StatusBadge label="Total Jobs" value={status.total_jobs.toString()} />
          <StatusBadge label="Active" value={status.active_jobs.toString()} active />
          <StatusBadge
            label="Running Now"
            value={status.running_jobs.toString()}
            active={status.running_jobs > 0}
          />
          <button
            onClick={() => {
              fetchJobs();
              fetchStatus();
            }}
            className="ml-auto px-3 py-1 text-xs font-theme-data text-[var(--accent)] hover:bg-[var(--accent)]/10 rounded transition-colors"
          >
            [REFRESH]
          </button>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 border-b border-[var(--accent)]/30 pb-2">
        {(['jobs', 'create', 'history'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            disabled={tab === 'history' && !selectedJob}
            className={`px-4 py-2 text-xs font-theme-data rounded-t transition-colors ${
              activeTab === tab
                ? 'bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/50 border-b-0'
                : 'text-text-muted hover:text-[var(--accent)] hover:bg-[var(--accent)]/5 disabled:opacity-50 disabled:cursor-not-allowed'
            }`}
          >
            [{tab.toUpperCase()}]
          </button>
        ))}
      </div>

      {/* Jobs List Tab */}
      {activeTab === 'jobs' && (
        <div className="space-y-4">
          {jobs.length === 0 ? (
            <div className="text-center py-12 bg-surface border border-border rounded-lg">
              <div className="text-4xl mb-4">📅</div>
              <h3 className="text-lg font-theme-data font-bold text-text mb-2">
                No scheduled jobs
              </h3>
              <p className="text-text-muted mb-4">Create your first scheduled audit job</p>
              <button
                onClick={() => setActiveTab('create')}
                className="px-4 py-2 bg-[var(--accent)] text-bg font-theme-data font-bold hover:bg-[var(--accent)]/80 transition-colors rounded"
              >
                [CREATE JOB]
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              {jobs.map((job) => {
                const statusStyle = STATUS_STYLES[job.status];
                return (
                  <div
                    key={job.job_id}
                    className={`p-4 border rounded transition-all cursor-pointer ${
                      selectedJob?.job_id === job.job_id
                        ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                        : 'border-[var(--accent)]/20 hover:border-[var(--accent)]/50'
                    }`}
                    onClick={() => setSelectedJob(job)}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className={`w-2 h-2 rounded-full ${statusStyle.dot}`} />
                        <div>
                          <h4 className="font-theme-data text-text">{job.name}</h4>
                          <div className="flex gap-2 mt-1">
                            <span
                              className={`px-2 py-0.5 text-xs rounded ${statusStyle.bg} ${statusStyle.text}`}
                            >
                              {job.status.toUpperCase()}
                            </span>
                            <span className="px-2 py-0.5 text-xs rounded bg-surface text-text-muted">
                              {TRIGGER_TYPE_LABELS[job.trigger_type]}
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-4">
                        <div className="text-right text-xs font-theme-data text-text-muted">
                          <div>Next: {formatDate(job.next_run)}</div>
                          <div>Last: {formatDate(job.last_run)}</div>
                        </div>

                        <div className="flex gap-1">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleTrigger(job.job_id);
                            }}
                            className="px-2 py-1 text-xs font-theme-data text-[var(--accent)] hover:bg-[var(--accent)]/20 rounded"
                            title="Trigger now"
                          >
                            [RUN]
                          </button>
                          {job.status === 'active' ? (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handlePause(job.job_id);
                              }}
                              className="px-2 py-1 text-xs font-theme-data text-yellow-500 hover:bg-yellow-500/20 rounded"
                              title="Pause job"
                            >
                              [PAUSE]
                            </button>
                          ) : job.status === 'paused' ? (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleResume(job.job_id);
                              }}
                              className="px-2 py-1 text-xs font-theme-data text-[var(--accent)] hover:bg-[var(--accent)]/20 rounded"
                              title="Resume job"
                            >
                              [RESUME]
                            </button>
                          ) : null}
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDelete(job.job_id);
                            }}
                            className="px-2 py-1 text-xs font-theme-data text-red-400 hover:bg-red-500/20 rounded"
                            title="Delete job"
                          >
                            [DEL]
                          </button>
                        </div>
                      </div>
                    </div>

                    <div className="mt-2 flex gap-4 text-xs font-theme-data text-text-muted">
                      <span>Runs: {job.run_count}</span>
                      <span className={job.error_count > 0 ? 'text-red-400' : ''}>
                        Errors: {job.error_count}
                      </span>
                      <span className="text-text-muted/50">ID: {job.job_id}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Create Job Tab */}
      {activeTab === 'create' && (
        <form onSubmit={handleCreate} className="card p-6 space-y-4">
          <h3 className="text-lg font-theme-data text-[var(--accent)]">Create Scheduled Job</h3>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Job Name *
              </label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder="Daily Security Scan"
                required
                className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>

            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Trigger Type
              </label>
              <select
                value={formData.trigger_type}
                onChange={(e) =>
                  setFormData({ ...formData, trigger_type: e.target.value as TriggerType })
                }
                className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              >
                {Object.entries(TRIGGER_TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-theme-data text-text-muted mb-1">
              Description
            </label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="Describe what this job does..."
              className="w-full h-20 p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            />
          </div>

          {/* Trigger-specific fields */}
          {formData.trigger_type === 'cron' && (
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Cron Expression *
                <span className="ml-2 text-text-muted/50">(minute hour day month weekday)</span>
              </label>
              <input
                type="text"
                value={formData.cron}
                onChange={(e) => setFormData({ ...formData, cron: e.target.value })}
                placeholder="0 2 * * *"
                required
                className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
              <div className="mt-1 text-xs text-text-muted font-theme-data">
                Examples: &quot;0 2 * * *&quot; (daily 2 AM), &quot;0 */6 * * *&quot; (every 6
                hours), &quot;0 9 * * 1-5&quot; (weekdays 9 AM)
              </div>
            </div>
          )}

          {formData.trigger_type === 'interval' && (
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Interval (minutes) *
              </label>
              <input
                type="number"
                value={formData.interval_minutes}
                onChange={(e) =>
                  setFormData({ ...formData, interval_minutes: parseInt(e.target.value) || 60 })
                }
                min={1}
                required
                className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Audit Preset
              </label>
              <select
                value={formData.preset}
                onChange={(e) => setFormData({ ...formData, preset: e.target.value })}
                className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              >
                <option value="">Select preset...</option>
                <option value="Code Security">Code Security</option>
                <option value="Code Quality">Code Quality</option>
                <option value="Compliance">Compliance</option>
                <option value="Full Audit">Full Audit</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Workspace ID
              </label>
              <input
                type="text"
                value={formData.workspace_id}
                onChange={(e) => setFormData({ ...formData, workspace_id: e.target.value })}
                placeholder="ws_123"
                className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Severity Threshold
              </label>
              <select
                value={formData.finding_severity_threshold}
                onChange={(e) =>
                  setFormData({ ...formData, finding_severity_threshold: e.target.value })
                }
                className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Tags (comma-separated)
              </label>
              <input
                type="text"
                value={formData.tags}
                onChange={(e) => setFormData({ ...formData, tags: e.target.value })}
                placeholder="security, daily, production"
                className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
          </div>

          <div className="flex gap-4">
            <label className="flex items-center gap-2 text-sm font-theme-data">
              <input
                type="checkbox"
                checked={formData.notify_on_complete}
                onChange={(e) => setFormData({ ...formData, notify_on_complete: e.target.checked })}
                className="rounded border-[var(--accent)]/30"
              />
              <span className="text-text-muted">Notify on completion</span>
            </label>

            <label className="flex items-center gap-2 text-sm font-theme-data">
              <input
                type="checkbox"
                checked={formData.notify_on_findings}
                onChange={(e) => setFormData({ ...formData, notify_on_findings: e.target.checked })}
                className="rounded border-[var(--accent)]/30"
              />
              <span className="text-text-muted">Notify on findings</span>
            </label>
          </div>

          <div className="flex gap-3">
            <button
              type="submit"
              disabled={createLoading || !formData.name}
              className="px-6 py-2 text-sm font-theme-data bg-[var(--accent)] text-bg font-bold rounded hover:bg-[var(--accent)]/80 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {createLoading ? '[CREATING...]' : '[CREATE JOB]'}
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('jobs')}
              className="px-4 py-2 text-sm font-theme-data text-text-muted hover:text-text transition-colors"
            >
              [CANCEL]
            </button>
          </div>
        </form>
      )}

      {/* History Tab */}
      {activeTab === 'history' && selectedJob && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-theme-data text-[var(--accent)]">
              Run History: {selectedJob.name}
            </h3>
            <button
              onClick={() => fetchJobHistory(selectedJob.job_id)}
              disabled={historyLoading}
              className="px-3 py-1 text-xs font-theme-data text-[var(--accent)] hover:bg-[var(--accent)]/10 rounded"
            >
              {historyLoading ? '[LOADING...]' : '[REFRESH]'}
            </button>
          </div>

          {historyLoading ? (
            <div className="animate-pulse space-y-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-16 bg-surface rounded" />
              ))}
            </div>
          ) : jobHistory.length === 0 ? (
            <div className="text-center py-8 bg-surface border border-border rounded">
              <p className="text-text-muted font-theme-data">No run history yet</p>
            </div>
          ) : (
            <div className="space-y-2">
              {jobHistory.map((run) => (
                <div
                  key={run.run_id}
                  className="p-3 border border-[var(--accent)]/20 rounded bg-surface"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <RunStatusBadge status={run.status} />
                      <span className="text-sm font-theme-data text-text-muted">
                        {formatDate(run.started_at)}
                      </span>
                    </div>
                    <div className="flex items-center gap-4 text-xs font-theme-data text-text-muted">
                      <span>Duration: {formatDuration(run.duration_ms)}</span>
                      <span>Findings: {run.findings_count}</span>
                      {run.session_id && (
                        <span className="text-[var(--acid-cyan)]">Session: {run.session_id}</span>
                      )}
                    </div>
                  </div>
                  {run.error_message && (
                    <div className="mt-2 text-xs font-theme-data text-red-400 bg-red-500/10 p-2 rounded">
                      {run.error_message}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ label, value, active }: { label: string; value: string; active?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-theme-data text-text-muted">{label}:</span>
      <span className={`text-xs font-theme-data ${active ? 'text-[var(--accent)]' : 'text-text'}`}>
        {value}
      </span>
    </div>
  );
}

function RunStatusBadge({ status }: { status: string }) {
  const styles: Record<string, { bg: string; text: string }> = {
    completed: { bg: 'bg-[var(--accent)]/20', text: 'text-[var(--accent)]' },
    running: { bg: 'bg-[var(--acid-cyan)]/20', text: 'text-[var(--acid-cyan)]' },
    timeout: { bg: 'bg-yellow-500/20', text: 'text-yellow-500' },
    error: { bg: 'bg-red-500/20', text: 'text-red-400' },
  };
  const style = styles[status] || styles.error;

  return (
    <span
      className={`px-2 py-0.5 text-xs rounded ${style.bg} ${style.text} font-theme-data uppercase`}
    >
      {status}
    </span>
  );
}
