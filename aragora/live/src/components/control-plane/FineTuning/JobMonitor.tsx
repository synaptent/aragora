'use client';

import { useState } from 'react';
import type { FineTuningJob } from './FineTuningDashboard';

export interface JobMonitorProps {
  jobs: FineTuningJob[];
  onCancelJob?: (jobId: string) => void;
  onViewJob?: (job: FineTuningJob) => void;
  className?: string;
}

const STATUS_COLORS: Record<FineTuningJob['status'], { bg: string; text: string }> = {
  queued: { bg: 'bg-yellow-900/30', text: 'text-yellow-400' },
  preparing: { bg: 'bg-cyan-900/30', text: 'text-cyan-400' },
  training: { bg: 'bg-[var(--accent)]/20', text: 'text-[var(--accent)]' },
  completed: { bg: 'bg-green-900/30', text: 'text-green-400' },
  failed: { bg: 'bg-red-900/30', text: 'text-red-400' },
  cancelled: { bg: 'bg-gray-900/30', text: 'text-gray-400' },
};

const VERTICAL_ICONS: Record<string, string> = {
  software: '&#x1F4BB;',
  legal: '&#x2696;',
  healthcare: '&#x1F3E5;',
  accounting: '&#x1F4CA;',
  research: '&#x1F52C;',
};

export function JobMonitor({ jobs, onCancelJob, onViewJob, className = '' }: JobMonitorProps) {
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('all');

  const filteredJobs =
    statusFilter === 'all' ? jobs : jobs.filter((j) => j.status === statusFilter);

  const formatDuration = (start?: string, end?: string) => {
    if (!start) return '-';
    const startTime = new Date(start).getTime();
    const endTime = end ? new Date(end).getTime() : Date.now();
    const seconds = Math.floor((endTime - startTime) / 1000);
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (hours > 0) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
  };

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString();
  };

  return (
    <div className={className}>
      {/* Filter */}
      <div className="flex items-center gap-2 mb-4">
        <span className="text-xs text-text-muted">Filter:</span>
        {['all', 'training', 'queued', 'completed', 'failed'].map((status) => (
          <button
            key={status}
            onClick={() => setStatusFilter(status)}
            className={`px-2 py-1 text-xs font-theme-data rounded transition-colors ${
              statusFilter === status
                ? 'bg-[var(--accent)] text-bg'
                : 'bg-surface text-text-muted hover:text-text'
            }`}
          >
            {status.charAt(0).toUpperCase() + status.slice(1)}
          </button>
        ))}
      </div>

      {/* Job List */}
      {filteredJobs.length === 0 ? (
        <div className="text-center py-8 text-text-muted">
          <p className="mt-4">No fine-tuning jobs found</p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredJobs.map((job) => {
            const isExpanded = expandedJobId === job.id;
            const colors = STATUS_COLORS[job.status];

            return (
              <div
                key={job.id}
                className={`bg-bg border rounded-lg overflow-hidden transition-all ${
                  isExpanded ? 'border-[var(--accent)]' : 'border-border'
                }`}
              >
                {/* Job Header */}
                <div
                  onClick={() => setExpandedJobId(isExpanded ? null : job.id)}
                  className="p-4 cursor-pointer hover:bg-surface/50 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span
                        className="text-xl"
                        dangerouslySetInnerHTML={{
                          __html: VERTICAL_ICONS[job.vertical] || '&#x1F4BB;',
                        }}
                      />
                      <div>
                        <h4 className="font-theme-data font-bold text-text">{job.name}</h4>
                        <p className="text-xs text-text-muted mt-0.5">{job.baseModel}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span
                        className={`px-2 py-1 text-xs font-theme-data uppercase rounded ${colors.bg} ${colors.text}`}
                      >
                        {job.status}
                      </span>
                    </div>
                  </div>

                  {/* Progress Bar (for training jobs) */}
                  {(job.status === 'training' || job.status === 'preparing') && (
                    <div className="mt-3">
                      <div className="flex items-center justify-between text-xs mb-1">
                        <span className="text-text-muted">
                          Epoch {job.currentEpoch || 1}/{job.totalEpochs || 3}
                          {job.currentStep && ` | Step ${job.currentStep}/${job.totalSteps}`}
                        </span>
                        <span className="font-theme-data text-[var(--accent)]">
                          {Math.round(job.progress * 100)}%
                        </span>
                      </div>
                      <div className="h-2 bg-surface rounded-full overflow-hidden">
                        <div
                          className="h-full bg-[var(--accent)] transition-all duration-500"
                          style={{ width: `${job.progress * 100}%` }}
                        />
                      </div>
                      {job.loss !== undefined && (
                        <div className="text-xs text-text-muted mt-1">
                          Loss:{' '}
                          <span className="font-theme-data text-cyan-400">
                            {job.loss.toFixed(4)}
                          </span>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Expanded Details */}
                {isExpanded && (
                  <div className="px-4 pb-4 border-t border-border pt-4">
                    <div className="grid grid-cols-2 gap-4 text-xs">
                      <div>
                        <span className="text-text-muted">Training Examples:</span>
                        <span className="font-theme-data text-text ml-2">
                          {job.trainingExamples.toLocaleString()}
                        </span>
                      </div>
                      <div>
                        <span className="text-text-muted">Duration:</span>
                        <span className="font-theme-data text-text ml-2">
                          {formatDuration(job.startedAt, job.completedAt)}
                        </span>
                      </div>
                      <div>
                        <span className="text-text-muted">Started:</span>
                        <span className="font-theme-data text-text ml-2">
                          {formatDate(job.startedAt)}
                        </span>
                      </div>
                      <div>
                        <span className="text-text-muted">Completed:</span>
                        <span className="font-theme-data text-text ml-2">
                          {formatDate(job.completedAt)}
                        </span>
                      </div>
                    </div>

                    {job.outputPath && (
                      <div className="mt-3 p-2 bg-surface border border-border rounded">
                        <span className="text-xs text-text-muted">Output:</span>
                        <code className="block text-xs font-theme-data text-[var(--acid-cyan)] mt-1">
                          {job.outputPath}
                        </code>
                      </div>
                    )}

                    {job.error && (
                      <div className="mt-3 p-2 bg-red-900/20 border border-red-800/30 rounded">
                        <span className="text-xs text-red-400">Error:</span>
                        <code className="block text-xs font-theme-data text-red-300 mt-1">
                          {job.error}
                        </code>
                      </div>
                    )}

                    {/* Actions */}
                    <div className="flex gap-2 mt-4">
                      {(job.status === 'training' ||
                        job.status === 'preparing' ||
                        job.status === 'queued') && (
                        <button
                          onClick={() => onCancelJob?.(job.id)}
                          className="px-3 py-1.5 text-xs font-theme-data bg-red-900/30 text-red-400 border border-red-800/30 rounded hover:bg-red-900/50 transition-colors"
                        >
                          Cancel
                        </button>
                      )}
                      {job.status === 'completed' && job.outputPath && (
                        <button
                          onClick={() => onViewJob?.(job)}
                          className="px-3 py-1.5 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/30 rounded hover:bg-[var(--accent)]/30 transition-colors"
                        >
                          Load Adapter
                        </button>
                      )}
                      <button
                        onClick={() => onViewJob?.(job)}
                        className="px-3 py-1.5 text-xs font-theme-data bg-surface border border-border rounded hover:border-text-muted transition-colors"
                      >
                        View Details
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
