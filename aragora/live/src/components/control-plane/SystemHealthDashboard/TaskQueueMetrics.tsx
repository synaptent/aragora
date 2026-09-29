'use client';

import React from 'react';

export interface QueueMetrics {
  pending: number;
  running: number;
  completed_today: number;
  failed_today: number;
  avg_wait_time_ms: number;
  avg_execution_time_ms: number;
  throughput_per_minute: number;
}

export interface TaskQueueMetricsProps {
  metrics: QueueMetrics | null;
  loading?: boolean;
}

function formatTime(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms / 60000)}m`;
}

export function TaskQueueMetrics({ metrics, loading = false }: TaskQueueMetricsProps) {
  if (loading) {
    return (
      <div className="bg-surface border border-[var(--accent)]/30 p-4 animate-pulse">
        <div className="w-32 h-4 bg-[var(--accent)]/20 rounded mb-4" />
        <div className="grid grid-cols-2 gap-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-16 bg-bg rounded" />
          ))}
        </div>
      </div>
    );
  }

  const displayMetrics = metrics ?? {
    pending: 0,
    running: 0,
    completed_today: 0,
    failed_today: 0,
    avg_wait_time_ms: 0,
    avg_execution_time_ms: 0,
    throughput_per_minute: 0,
  };

  const failureRate =
    displayMetrics.completed_today + displayMetrics.failed_today > 0
      ? (displayMetrics.failed_today /
          (displayMetrics.completed_today + displayMetrics.failed_today)) *
        100
      : 0;

  return (
    <div className="bg-surface border border-[var(--accent)]/30 p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs font-theme-data text-[var(--accent)] uppercase">
          {'>'} TASK QUEUE
        </span>
        <span className="text-xs font-theme-data text-text-muted">
          {displayMetrics.throughput_per_minute.toFixed(1)}/min
        </span>
      </div>

      {/* Main metrics grid */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div className="bg-bg p-3 rounded text-center">
          <div className="text-2xl font-theme-data text-[var(--acid-yellow)]">
            {displayMetrics.pending}
          </div>
          <div className="text-xs font-theme-data text-text-muted">PENDING</div>
        </div>
        <div className="bg-bg p-3 rounded text-center">
          <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
            {displayMetrics.running}
          </div>
          <div className="text-xs font-theme-data text-text-muted">RUNNING</div>
        </div>
        <div className="bg-bg p-3 rounded text-center">
          <div className="text-2xl font-theme-data text-success">
            {displayMetrics.completed_today}
          </div>
          <div className="text-xs font-theme-data text-text-muted">COMPLETED</div>
        </div>
        <div className="bg-bg p-3 rounded text-center">
          <div
            className={`text-2xl font-theme-data ${displayMetrics.failed_today > 0 ? 'text-[var(--crimson)]' : 'text-text-muted'}`}
          >
            {displayMetrics.failed_today}
          </div>
          <div className="text-xs font-theme-data text-text-muted">FAILED</div>
        </div>
      </div>

      {/* Performance metrics */}
      <div className="space-y-2 pt-3 border-t border-border/50">
        <div className="flex items-center justify-between">
          <span className="text-xs font-theme-data text-text-muted">Avg Wait Time</span>
          <span className="text-sm font-theme-data text-text">
            {formatTime(displayMetrics.avg_wait_time_ms)}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs font-theme-data text-text-muted">Avg Execution</span>
          <span className="text-sm font-theme-data text-text">
            {formatTime(displayMetrics.avg_execution_time_ms)}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs font-theme-data text-text-muted">Failure Rate</span>
          <span
            className={`text-sm font-theme-data ${
              failureRate > 10
                ? 'text-[var(--crimson)]'
                : failureRate > 5
                  ? 'text-[var(--acid-yellow)]'
                  : 'text-success'
            }`}
          >
            {failureRate.toFixed(1)}%
          </span>
        </div>
      </div>
    </div>
  );
}
