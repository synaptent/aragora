'use client';

/**
 * ExecutionProgressOverlay - Real-time execution progress overlay for the pipeline canvas.
 *
 * Shows stage progress dots, subtask counter, streamed node count, elapsed timer,
 * and a success/failure result badge during pipeline execution.
 */

import { memo, useState, useEffect, useRef, useCallback } from 'react';
import type { PipelineStageType } from './types';

const STAGES: PipelineStageType[] = ['ideas', 'principles', 'goals', 'actions', 'orchestration'];

const STAGE_LABELS: Record<PipelineStageType, string> = {
  ideas: 'Ideas',
  principles: 'Principles',
  goals: 'Goals',
  actions: 'Actions',
  orchestration: 'Orchestration',
};

export interface ExecutionEvent {
  nodeId: string;
  label?: string;
  status: string;
  timestamp: number;
}

export interface ExecutionProgressOverlayProps {
  /** Whether the pipeline is currently executing */
  executing: boolean;
  /** Current active stage name */
  currentStage?: string;
  /** Stages that have completed */
  completedStages: string[];
  /** Number of nodes streamed via WebSocket */
  streamedNodeCount: number;
  /** Number of completed subtasks */
  completedSubtasks: number;
  /** Total number of subtasks */
  totalSubtasks: number;
  /** Final execution status */
  executeStatus: 'idle' | 'success' | 'failed';
  /** Recent execution events for the mini-log */
  recentEvents?: ExecutionEvent[];
}

function useElapsedTimer(running: boolean): number {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number>(0);

  useEffect(() => {
    if (!running) {
      setElapsed(0);
      return;
    }
    startRef.current = Date.now();
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [running]);

  return elapsed;
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export const ExecutionProgressOverlay = memo(function ExecutionProgressOverlay({
  executing,
  currentStage,
  completedStages,
  streamedNodeCount,
  completedSubtasks,
  totalSubtasks,
  executeStatus,
  recentEvents = [],
}: ExecutionProgressOverlayProps) {
  const elapsed = useElapsedTimer(executing);
  const [visible, setVisible] = useState(false);
  const fadeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Show overlay when executing starts, fade out on completion
  useEffect(() => {
    if (executing) {
      setVisible(true);
      if (fadeTimerRef.current) clearTimeout(fadeTimerRef.current);
    } else if (executeStatus !== 'idle') {
      // Show result briefly after completion/failure, then fade out
      setVisible(true);
      fadeTimerRef.current = setTimeout(() => setVisible(false), 3000);
    } else {
      setVisible(false);
    }
    return () => {
      if (fadeTimerRef.current) clearTimeout(fadeTimerRef.current);
    };
  }, [executing, executeStatus]);

  const getStageState = useCallback(
    (stage: PipelineStageType): 'completed' | 'active' | 'pending' => {
      if (completedStages.includes(stage)) return 'completed';
      if (currentStage === stage) return 'active';
      return 'pending';
    },
    [completedStages, currentStage],
  );

  if (!visible) return null;

  const progressPct = totalSubtasks > 0 ? (completedSubtasks / totalSubtasks) * 100 : 0;
  const isDone = executeStatus === 'success' || executeStatus === 'failed';

  return (
    <div
      data-testid="execution-progress-overlay"
      className={`absolute inset-0 z-40 flex items-center justify-center pointer-events-none transition-opacity duration-500 ${
        isDone && !executing ? 'opacity-0' : 'opacity-100'
      }`}
    >
      <div className="pointer-events-auto bg-surface/95 border border-border rounded-xl shadow-2xl px-8 py-6 min-w-[340px] max-w-md">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-theme-data font-bold text-text uppercase tracking-wide">
            {isDone ? 'Execution Complete' : 'Executing Pipeline'}
          </h3>
          {executing && (
            <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
          )}
        </div>

        {/* Stage progress dots */}
        <div className="flex items-center gap-2 mb-4">
          {STAGES.map((stage, i) => {
            const state = getStageState(stage);
            return (
              <div key={stage} className="flex items-center">
                <div className="flex flex-col items-center">
                  <div
                    data-testid={`stage-dot-${stage}`}
                    className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-theme-data font-bold border-2 transition-all ${
                      state === 'completed'
                        ? 'bg-emerald-500/30 border-emerald-400 text-emerald-300'
                        : state === 'active'
                          ? 'bg-amber-500/30 border-amber-400 text-amber-300 animate-pulse'
                          : 'bg-gray-500/20 border-gray-600 text-gray-500'
                    }`}
                  >
                    {state === 'completed' ? '\u2713' : i + 1}
                  </div>
                  <span
                    className={`text-[9px] font-theme-data mt-1 ${
                      state === 'completed'
                        ? 'text-emerald-400'
                        : state === 'active'
                          ? 'text-amber-300'
                          : 'text-text-muted/50'
                    }`}
                  >
                    {STAGE_LABELS[stage]}
                  </span>
                </div>
                {i < STAGES.length - 1 && (
                  <div
                    className={`w-6 h-0.5 mx-1 mb-4 ${
                      completedStages.includes(stage) ? 'bg-emerald-500/50' : 'bg-gray-600/30'
                    }`}
                  />
                )}
              </div>
            );
          })}
        </div>

        {/* Progress bar */}
        {totalSubtasks > 0 && (
          <div className="mb-3">
            <div className="flex justify-between text-[10px] font-theme-data text-text-muted mb-1">
              <span data-testid="subtask-count">
                {completedSubtasks}/{totalSubtasks} subtasks
              </span>
              <span>{Math.round(progressPct)}%</span>
            </div>
            <div className="w-full h-1.5 bg-bg rounded-full overflow-hidden">
              <div
                className="h-full bg-[var(--accent)] rounded-full transition-all duration-300"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        )}

        {/* Stats row */}
        <div className="flex items-center justify-between text-[11px] font-theme-data text-text-muted">
          <div className="flex items-center gap-3">
            {streamedNodeCount > 0 && (
              <span data-testid="streamed-count">
                {streamedNodeCount} node{streamedNodeCount !== 1 ? 's' : ''} streamed
              </span>
            )}
          </div>
          <span data-testid="elapsed-timer">{formatElapsed(elapsed)}</span>
        </div>

        {/* Mini event log */}
        {recentEvents.length > 0 && (
          <div className="mt-3 space-y-1 max-h-[100px] overflow-y-auto">
            {recentEvents.slice(-5).map((evt, i) => (
              <div
                key={`${evt.nodeId}-${i}`}
                className={`flex items-center gap-1.5 text-[10px] font-theme-data ${
                  evt.status === 'succeeded'
                    ? 'text-emerald-400'
                    : evt.status === 'failed'
                      ? 'text-red-400'
                      : evt.status === 'in_progress'
                        ? 'text-amber-300'
                        : 'text-text-muted'
                }`}
              >
                {evt.status === 'in_progress' && (
                  <span className="inline-block w-1.5 h-1.5 border border-current border-t-transparent rounded-full animate-spin" />
                )}
                {evt.status === 'succeeded' && <span>✓</span>}
                {evt.status === 'failed' && <span>✗</span>}
                {evt.status === 'pending' && <span>·</span>}
                <span className="truncate">{evt.label || evt.nodeId}</span>
                <span className="text-text-muted/50 ml-auto">{evt.status.replace('_', ' ')}</span>
              </div>
            ))}
          </div>
        )}

        {/* Result badge */}
        {isDone && (
          <div
            data-testid="result-badge"
            className={`mt-4 text-center py-2 rounded text-xs font-theme-data font-bold ${
              executeStatus === 'success'
                ? 'bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/50'
                : 'bg-red-500/20 text-red-300 ring-1 ring-red-500/50'
            }`}
          >
            {executeStatus === 'success' ? '\u2713 Pipeline Succeeded' : '\u2717 Pipeline Failed'}
          </div>
        )}
      </div>
    </div>
  );
});

export default ExecutionProgressOverlay;
