'use client';

import { memo, useState } from 'react';
import { DiffPreview } from './DiffPreview';

export interface ApprovalGateProps {
  agentId: string;
  agentName: string;
  taskDescription: string;
  diffPreview?: string;
  testResults?: { passed: number; failed: number; skipped: number };
  onApprove: (agentId: string, notes?: string) => void;
  onReject: (agentId: string, feedback: string) => void;
  onClose: () => void;
}

export const ApprovalGate = memo(function ApprovalGate({
  agentId,
  agentName,
  taskDescription,
  diffPreview,
  testResults,
  onApprove,
  onReject,
  onClose,
}: ApprovalGateProps) {
  const [mode, setMode] = useState<'review' | 'reject'>('review');
  const [feedback, setFeedback] = useState('');
  const [approveNotes, setApproveNotes] = useState('');

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      data-testid="approval-gate"
    >
      <div className="w-full max-w-2xl max-h-[80vh] bg-[var(--surface)] border border-[var(--border)] rounded-lg shadow-xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
          <div className="flex items-center gap-2">
            <span className="text-base">🔔</span>
            <span className="text-sm font-theme-data font-bold text-amber-400">
              Approval Required
            </span>
          </div>
          <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text)]">
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Agent & task info */}
          <div className="space-y-1">
            <div className="text-xs font-theme-data text-[var(--text-muted)]">Agent</div>
            <div className="text-sm font-theme-data text-[var(--text)]">{agentName}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs font-theme-data text-[var(--text-muted)]">Task</div>
            <div className="text-sm text-[var(--text)]">{taskDescription}</div>
          </div>

          {/* Test results */}
          {testResults && (
            <div className="space-y-1">
              <div className="text-xs font-theme-data text-[var(--text-muted)]">Test Results</div>
              <div className="flex gap-3 text-xs font-theme-data">
                <span className="text-emerald-400">✓ {testResults.passed} passed</span>
                {testResults.failed > 0 && (
                  <span className="text-red-400">✗ {testResults.failed} failed</span>
                )}
                {testResults.skipped > 0 && (
                  <span className="text-gray-400">○ {testResults.skipped} skipped</span>
                )}
              </div>
            </div>
          )}

          {/* Diff */}
          {diffPreview && <DiffPreview diff={diffPreview} maxLines={30} />}

          {/* Reject feedback */}
          {mode === 'reject' && (
            <div className="space-y-1.5">
              <div className="text-xs font-theme-data text-[var(--text-muted)]">
                Rejection Feedback
              </div>
              <textarea
                className="w-full text-sm font-theme-data bg-[var(--bg)] text-[var(--text)] border border-[var(--border)] rounded p-3 resize-none"
                placeholder="Explain what needs to change..."
                rows={3}
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                autoFocus
              />
            </div>
          )}

          {/* Approve notes (optional) */}
          {mode === 'review' && (
            <div className="space-y-1.5">
              <div className="text-xs font-theme-data text-[var(--text-muted)]">
                Notes (optional)
              </div>
              <input
                className="w-full text-sm font-theme-data bg-[var(--bg)] text-[var(--text)] border border-[var(--border)] rounded px-3 py-2"
                placeholder="Any notes for the record..."
                value={approveNotes}
                onChange={(e) => setApproveNotes(e.target.value)}
              />
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-3 px-4 py-3 border-t border-[var(--border)]">
          {mode === 'review' ? (
            <>
              <button
                className="flex-1 px-4 py-2 text-sm font-theme-data bg-emerald-500/20 text-emerald-400 rounded-lg hover:bg-emerald-500/30 transition-colors"
                onClick={() => onApprove(agentId, approveNotes || undefined)}
              >
                ✓ Approve & Continue
              </button>
              <button
                className="flex-1 px-4 py-2 text-sm font-theme-data bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 transition-colors"
                onClick={() => setMode('reject')}
              >
                ✗ Reject
              </button>
              <button
                className="px-4 py-2 text-sm font-theme-data text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
                onClick={onClose}
              >
                Later
              </button>
            </>
          ) : (
            <>
              <button
                className="flex-1 px-4 py-2 text-sm font-theme-data bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 transition-colors"
                onClick={() => {
                  onReject(agentId, feedback);
                  setMode('review');
                  setFeedback('');
                }}
                disabled={!feedback.trim()}
              >
                Send Rejection
              </button>
              <button
                className="px-4 py-2 text-sm font-theme-data text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
                onClick={() => setMode('review')}
              >
                Back
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
});

export default ApprovalGate;
