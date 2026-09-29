'use client';

import type { ExecutionStep, StepStatus } from '@/hooks/useWorkflowExecution';

export interface ExecutionTimelineProps {
  /** List of steps in the execution */
  steps: ExecutionStep[];
  /** Currently running step ID */
  currentStepId?: string;
  /** Callback when a step is clicked */
  onStepClick?: (step: ExecutionStep) => void;
}

const statusStyles: Record<StepStatus, { bg: string; border: string; dot: string; text: string }> =
  {
    pending: {
      bg: 'bg-gray-900/20',
      border: 'border-gray-700',
      dot: 'bg-gray-500',
      text: 'text-gray-400',
    },
    running: {
      bg: 'bg-blue-900/20',
      border: 'border-blue-700',
      dot: 'bg-blue-400 animate-pulse',
      text: 'text-blue-400',
    },
    completed: {
      bg: 'bg-green-900/20',
      border: 'border-green-700',
      dot: 'bg-green-400',
      text: 'text-green-400',
    },
    failed: {
      bg: 'bg-red-900/20',
      border: 'border-red-700',
      dot: 'bg-red-400',
      text: 'text-red-400',
    },
    skipped: {
      bg: 'bg-yellow-900/20',
      border: 'border-yellow-700',
      dot: 'bg-yellow-400',
      text: 'text-yellow-400',
    },
  };

const statusLabels: Record<StepStatus, string> = {
  pending: 'Pending',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  skipped: 'Skipped',
};

const stepTypeIcons: Record<string, string> = {
  agent: '🤖',
  debate: '💬',
  quick_debate: '⚡',
  parallel: '⏸',
  conditional: '❓',
  loop: '🔄',
  human_checkpoint: '👤',
  memory_read: '📖',
  memory_write: '📝',
  task: '📋',
};

/**
 * Timeline visualization for workflow execution steps.
 */
export function ExecutionTimeline({ steps, currentStepId, onStepClick }: ExecutionTimelineProps) {
  if (steps.length === 0) {
    return (
      <div className="text-center py-8 text-text-muted">
        <p>No steps to display</p>
      </div>
    );
  }

  return (
    <div className="relative">
      {/* Timeline line */}
      <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-border" />

      {/* Steps */}
      <div className="space-y-4">
        {steps.map((step, index) => {
          const styles = statusStyles[step.status];
          const isCurrent = step.id === currentStepId;

          return (
            <div
              key={step.id}
              onClick={() => onStepClick?.(step)}
              className={`
                relative pl-10 cursor-pointer transition-all
                ${isCurrent ? 'scale-[1.02]' : 'hover:scale-[1.01]'}
              `}
            >
              {/* Timeline dot */}
              <div
                className={`
                  absolute left-2 top-3 w-4 h-4 rounded-full
                  ${styles.dot}
                  ${isCurrent ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg' : ''}
                `}
              />

              {/* Step card */}
              <div
                className={`
                  p-3 rounded-lg border transition-colors
                  ${styles.bg} ${styles.border}
                  ${isCurrent ? 'border-[var(--accent)]' : ''}
                `}
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-lg">{stepTypeIcons[step.step_type] || '📦'}</span>
                    <div>
                      <div className="text-sm font-theme-data text-text">{step.name}</div>
                      <div className="text-xs text-text-muted">{step.step_type}</div>
                    </div>
                  </div>

                  <div
                    className={`
                      px-2 py-1 text-xs font-theme-data rounded
                      ${styles.bg} ${styles.text}
                    `}
                  >
                    {statusLabels[step.status]}
                  </div>
                </div>

                {/* Progress/Duration */}
                {(step.duration_ms !== undefined || step.status === 'running') && (
                  <div className="flex items-center justify-between text-xs mb-2">
                    <span className="text-text-muted">
                      {step.status === 'running'
                        ? 'In progress...'
                        : `Duration: ${(step.duration_ms! / 1000).toFixed(1)}s`}
                    </span>

                    {step.tokens_used !== undefined && (
                      <span className="text-text-muted">
                        {step.tokens_used.toLocaleString()} tokens
                      </span>
                    )}
                  </div>
                )}

                {/* Error message */}
                {step.status === 'failed' && step.error && (
                  <div className="mt-2 p-2 bg-red-900/10 border border-red-800/30 rounded text-xs text-red-400">
                    {step.error}
                  </div>
                )}

                {/* Cost */}
                {step.cost_usd !== undefined && step.cost_usd > 0 && (
                  <div className="mt-2 text-xs text-text-muted">
                    Cost: ${step.cost_usd.toFixed(4)}
                  </div>
                )}
              </div>

              {/* Connection line to next step */}
              {index < steps.length - 1 && (
                <div
                  className={`
                    absolute left-[15px] top-[52px] w-0.5 h-4
                    ${step.status === 'completed' ? 'bg-green-600' : 'bg-border'}
                  `}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default ExecutionTimeline;
