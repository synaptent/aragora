'use client';

import { useState, useCallback } from 'react';
import type { ApprovalRequest } from '@/hooks/useWorkflowExecution';

export interface ApprovalQueueProps {
  /** List of pending approval requests */
  requests: ApprovalRequest[];
  /** Callback when an approval is resolved */
  onResolve: (requestId: string, approved: boolean, notes?: string) => void;
  /** Loading state (request ID -> loading) */
  loadingStates?: Record<string, boolean>;
}

/**
 * Queue component for handling human approval requests in workflows.
 */
export function ApprovalQueue({ requests, onResolve, loadingStates = {} }: ApprovalQueueProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});

  const handleApprove = useCallback(
    (requestId: string) => {
      onResolve(requestId, true, notes[requestId]);
    },
    [onResolve, notes],
  );

  const handleReject = useCallback(
    (requestId: string) => {
      onResolve(requestId, false, notes[requestId]);
    },
    [onResolve, notes],
  );

  const toggleExpand = useCallback((id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  }, []);

  const updateNotes = useCallback((id: string, value: string) => {
    setNotes((prev) => ({ ...prev, [id]: value }));
  }, []);

  if (requests.length === 0) {
    return (
      <div className="text-center py-8">
        <div className="text-4xl mb-2">✓</div>
        <p className="text-text-muted">No pending approvals</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {requests.map((request) => {
        const isExpanded = expandedId === request.id;
        const isLoading = loadingStates[request.id];
        const isOverdue = request.deadline && new Date(request.deadline) < new Date();

        return (
          <div
            key={request.id}
            className={`
              border rounded-lg transition-all
              ${isOverdue ? 'border-red-700 bg-red-900/10' : 'border-border bg-surface/50'}
            `}
          >
            {/* Header */}
            <div
              onClick={() => toggleExpand(request.id)}
              className="flex items-center justify-between p-4 cursor-pointer hover:bg-surface/80 transition-colors"
            >
              <div className="flex items-center gap-3">
                <div
                  className={`
                    w-10 h-10 rounded-full flex items-center justify-center text-lg
                    ${isOverdue ? 'bg-red-900/30' : 'bg-yellow-900/30'}
                  `}
                >
                  👤
                </div>
                <div>
                  <div className="text-sm font-theme-data text-text">{request.step_name}</div>
                  <div className="text-xs text-text-muted">
                    Requested {new Date(request.requested_at).toLocaleString()}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                {isOverdue && (
                  <span className="px-2 py-1 text-xs bg-red-900/30 text-red-400 rounded">
                    Overdue
                  </span>
                )}
                <span className="text-text-muted">{isExpanded ? '▼' : '▶'}</span>
              </div>
            </div>

            {/* Expanded content */}
            {isExpanded && (
              <div className="px-4 pb-4 border-t border-border">
                {/* Prompt */}
                <div className="mt-4 p-3 bg-bg rounded border border-border">
                  <div className="text-xs text-text-muted mb-1">Approval Prompt</div>
                  <p className="text-sm text-text">{request.prompt}</p>
                </div>

                {/* Context */}
                {request.context && Object.keys(request.context).length > 0 && (
                  <div className="mt-3">
                    <div className="text-xs text-text-muted mb-1">Context</div>
                    <pre className="p-2 bg-bg rounded text-xs text-text-muted overflow-x-auto">
                      {JSON.stringify(request.context, null, 2)}
                    </pre>
                  </div>
                )}

                {/* Deadline */}
                {request.deadline && (
                  <div className="mt-3 text-xs">
                    <span className="text-text-muted">Deadline: </span>
                    <span className={isOverdue ? 'text-red-400' : 'text-text'}>
                      {new Date(request.deadline).toLocaleString()}
                    </span>
                  </div>
                )}

                {/* Notes input */}
                <div className="mt-4">
                  <label className="block text-xs text-text-muted mb-1">Notes (optional)</label>
                  <textarea
                    value={notes[request.id] || ''}
                    onChange={(e) => updateNotes(request.id, e.target.value)}
                    placeholder="Add any notes or comments..."
                    className="w-full px-3 py-2 text-sm bg-bg border border-border rounded resize-none focus:border-[var(--accent)] focus:outline-none"
                    rows={2}
                    disabled={isLoading}
                  />
                </div>

                {/* Action buttons */}
                <div className="mt-4 flex items-center justify-end gap-3">
                  <button
                    onClick={() => handleReject(request.id)}
                    disabled={isLoading}
                    className="px-4 py-2 text-sm bg-red-900/30 text-red-400 rounded hover:bg-red-900/50 transition-colors disabled:opacity-50"
                  >
                    {isLoading ? 'Processing...' : 'Reject'}
                  </button>
                  <button
                    onClick={() => handleApprove(request.id)}
                    disabled={isLoading}
                    className="px-4 py-2 text-sm bg-green-900/30 text-green-400 rounded hover:bg-green-900/50 transition-colors disabled:opacity-50"
                  >
                    {isLoading ? 'Processing...' : 'Approve'}
                  </button>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default ApprovalQueue;
