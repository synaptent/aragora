'use client';

interface WorkflowStep {
  id: string;
  name: string;
  type: 'agent' | 'task' | 'decision' | 'human_checkpoint' | 'parallel' | 'memory';
  status: 'pending' | 'running' | 'completed' | 'failed' | 'waiting_approval';
  startedAt?: string;
  completedAt?: string;
  error?: string;
  output?: Record<string, unknown>;
  approvalRequired?: boolean;
  approvalMessage?: string;
}

interface StepDetailPanelProps {
  step: WorkflowStep | null;
  onClose: () => void;
  onApprove?: (stepId: string) => void;
  onReject?: (stepId: string) => void;
}

const STEP_ICONS: Record<string, string> = {
  agent: '🤖',
  task: '📋',
  decision: '🔀',
  human_checkpoint: '👤',
  parallel: '⚡',
  memory: '💾',
};

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  pending: { bg: 'bg-gray-900/30', text: 'text-gray-400' },
  running: { bg: 'bg-blue-900/30', text: 'text-blue-400' },
  completed: { bg: 'bg-green-900/30', text: 'text-green-400' },
  failed: { bg: 'bg-red-900/30', text: 'text-red-400' },
  waiting_approval: { bg: 'bg-purple-900/30', text: 'text-purple-400' },
};

function formatDateTime(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatDuration(startedAt: string, completedAt?: string): string {
  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : Date.now();
  const seconds = Math.floor((end - start) / 1000);

  if (seconds < 60) return `${seconds} seconds`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

export function StepDetailPanel({ step, onClose, onApprove, onReject }: StepDetailPanelProps) {
  if (!step) return null;

  const icon = STEP_ICONS[step.type] || '📦';
  const statusColors = STATUS_COLORS[step.status] || STATUS_COLORS.pending;

  return (
    <div className="fixed right-0 top-0 h-full w-full max-w-md bg-surface border-l border-border z-50 flex flex-col shadow-2xl">
      {/* Header */}
      <div className="p-4 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl">{icon}</span>
          <div>
            <h3 className="text-lg font-theme-data font-bold text-text">{step.name}</h3>
            <span className="text-xs font-theme-data text-text-muted uppercase">
              {step.type.replace('_', ' ')}
            </span>
          </div>
        </div>
        <button
          onClick={onClose}
          className="w-8 h-8 flex items-center justify-center text-text-muted hover:text-[var(--accent)] transition-colors"
        >
          <span className="text-xl">×</span>
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Status */}
        <div className={`p-4 rounded-lg ${statusColors.bg}`}>
          <div className="text-xs font-theme-data text-text-muted mb-1">STATUS</div>
          <div className={`text-lg font-theme-data font-bold ${statusColors.text} capitalize`}>
            {step.status.replace('_', ' ')}
          </div>
        </div>

        {/* Timing */}
        {step.startedAt && (
          <div className="space-y-3">
            <div className="p-3 bg-bg rounded border border-border">
              <div className="text-xs font-theme-data text-text-muted mb-1">STARTED AT</div>
              <div className="text-sm font-theme-data text-text">
                {formatDateTime(step.startedAt)}
              </div>
            </div>

            {step.completedAt && (
              <div className="p-3 bg-bg rounded border border-border">
                <div className="text-xs font-theme-data text-text-muted mb-1">COMPLETED AT</div>
                <div className="text-sm font-theme-data text-text">
                  {formatDateTime(step.completedAt)}
                </div>
              </div>
            )}

            <div className="p-3 bg-bg rounded border border-border">
              <div className="text-xs font-theme-data text-text-muted mb-1">DURATION</div>
              <div className="text-sm font-theme-data text-[var(--accent)]">
                {formatDuration(step.startedAt, step.completedAt)}
                {!step.completedAt && step.status === 'running' && (
                  <span className="text-blue-400 animate-pulse"> (running)</span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Error */}
        {step.error && (
          <div className="p-4 bg-red-900/20 border border-red-500/30 rounded-lg">
            <div className="text-xs font-theme-data text-red-400 mb-2">ERROR</div>
            <pre className="text-sm font-theme-data text-red-300 whitespace-pre-wrap break-words">
              {step.error}
            </pre>
          </div>
        )}

        {/* Approval Message */}
        {step.status === 'waiting_approval' && step.approvalMessage && (
          <div className="p-4 bg-purple-900/20 border border-purple-500/30 rounded-lg">
            <div className="text-xs font-theme-data text-purple-400 mb-2">APPROVAL REQUIRED</div>
            <p className="text-sm text-purple-200 mb-4">{step.approvalMessage}</p>
            <div className="flex gap-2">
              <button
                onClick={() => onApprove?.(step.id)}
                className="flex-1 py-2 bg-green-600 text-white font-theme-data text-sm rounded hover:bg-green-500 transition-colors"
              >
                Approve
              </button>
              <button
                onClick={() => onReject?.(step.id)}
                className="flex-1 py-2 bg-red-600 text-white font-theme-data text-sm rounded hover:bg-red-500 transition-colors"
              >
                Reject
              </button>
            </div>
          </div>
        )}

        {/* Output */}
        {step.output && Object.keys(step.output).length > 0 && (
          <div>
            <div className="text-xs font-theme-data text-text-muted mb-2">OUTPUT</div>
            <pre className="p-3 bg-bg border border-border rounded text-xs font-theme-data text-text overflow-x-auto max-h-64">
              {JSON.stringify(step.output, null, 2)}
            </pre>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-border">
        <button
          onClick={onClose}
          className="w-full py-2 border border-border text-text-muted font-theme-data text-sm rounded hover:border-text-muted transition-colors"
        >
          Close
        </button>
      </div>
    </div>
  );
}

export default StepDetailPanel;
