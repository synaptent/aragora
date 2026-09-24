'use client';

/**
 * StreamMetricsBar -- Real-time stream quality metrics display.
 *
 * Shows a compact status bar with:
 *   - TTFT (time to first token)
 *   - Token count
 *   - Average token latency
 *   - Stall count
 *   - Connection latency
 *   - Stream duration
 */

import type { StreamMetrics } from '@/hooks/useDebateStream';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface StreamMetricsBarProps {
  /** Stream metrics from useDebateStream. */
  metrics: StreamMetrics;
  /** Compact single-line mode. */
  compact?: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatMs(ms: number | null): string {
  if (ms === null) return '--';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function latencyColor(ms: number | null): string {
  if (ms === null) return 'text-text-muted';
  if (ms < 100) return 'text-[var(--accent)]';
  if (ms < 500) return 'text-[var(--acid-yellow)]';
  return 'text-red-400';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function StreamMetricsBar({ metrics, compact = false }: StreamMetricsBarProps) {
  if (compact) {
    return (
      <div className="flex items-center gap-3 text-[10px] font-theme-data text-text-muted">
        <span>
          TTFT: <span className={latencyColor(metrics.ttftMs)}>{formatMs(metrics.ttftMs)}</span>
        </span>
        <span>
          Tokens: <span className="text-[var(--accent)]">{metrics.tokenCount}</span>
        </span>
        {metrics.stallCount > 0 && (
          <span>
            Stalls: <span className="text-red-400">{metrics.stallCount}</span>
          </span>
        )}
        {metrics.connectionLatencyMs !== null && (
          <span>
            Lat:{' '}
            <span className={latencyColor(metrics.connectionLatencyMs)}>
              {formatMs(metrics.connectionLatencyMs)}
            </span>
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="bg-surface border border-border p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-theme-data text-text-muted uppercase tracking-wider">
          {'>'} STREAM QUALITY
        </span>
        {metrics.stallCount > 0 && (
          <span className="text-[10px] font-theme-data text-red-400 flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
            {metrics.stallCount} STALL{metrics.stallCount !== 1 ? 'S' : ''}
          </span>
        )}
        {metrics.stallCount === 0 && metrics.tokenCount > 0 && (
          <span className="text-[10px] font-theme-data text-[var(--accent)] flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" />
            HEALTHY
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {/* TTFT */}
        <div className="space-y-0.5">
          <div className="text-[9px] font-theme-data text-text-muted uppercase">TTFT</div>
          <div className={`text-xs font-theme-data font-bold ${latencyColor(metrics.ttftMs)}`}>
            {formatMs(metrics.ttftMs)}
          </div>
        </div>

        {/* Token Count */}
        <div className="space-y-0.5">
          <div className="text-[9px] font-theme-data text-text-muted uppercase">Tokens</div>
          <div className="text-xs font-theme-data font-bold text-[var(--accent)]">
            {metrics.tokenCount.toLocaleString()}
          </div>
        </div>

        {/* Avg Token Latency */}
        <div className="space-y-0.5">
          <div className="text-[9px] font-theme-data text-text-muted uppercase">Avg Latency</div>
          <div
            className={`text-xs font-theme-data font-bold ${latencyColor(metrics.avgTokenLatencyMs)}`}
          >
            {formatMs(metrics.avgTokenLatencyMs)}
          </div>
        </div>

        {/* Connection Latency */}
        <div className="space-y-0.5">
          <div className="text-[9px] font-theme-data text-text-muted uppercase">Conn. Lat</div>
          <div
            className={`text-xs font-theme-data font-bold ${latencyColor(metrics.connectionLatencyMs)}`}
          >
            {formatMs(metrics.connectionLatencyMs)}
          </div>
        </div>
      </div>

      {/* Stream duration */}
      {metrics.streamDurationMs !== null && (
        <div className="mt-2 pt-2 border-t border-border">
          <span className="text-[10px] font-theme-data text-text-muted">
            Total duration: {formatMs(metrics.streamDurationMs)}
          </span>
        </div>
      )}
    </div>
  );
}

export default StreamMetricsBar;
