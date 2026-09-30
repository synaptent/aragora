'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '@/config';

interface ApprovalRequest {
  id: string;
  title: string;
  description: string;
  changes: { file: string; action: string }[];
  risk_level: string;
  requested_at: string;
  requested_by: string;
  timeout_seconds: number;
  status: string;
  metadata: Record<string, unknown>;
}

interface ApprovalPanelProps {
  apiBase: string;
}

const RISK_COLORS: Record<string, { bg: string; text: string }> = {
  low: { bg: 'bg-[var(--accent)]/10', text: 'text-[var(--accent)]' },
  medium: { bg: 'bg-yellow-500/10', text: 'text-yellow-500' },
  high: { bg: 'bg-orange-500/10', text: 'text-orange-400' },
  critical: { bg: 'bg-red-500/10', text: 'text-red-400' },
};

export function ApprovalPanel({ apiBase }: ApprovalPanelProps) {
  const [requests, setRequests] = useState<ApprovalRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedRequest, setSelectedRequest] = useState<ApprovalRequest | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchRequests = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await apiFetch<{ pending: ApprovalRequest[] }>(
        `${apiBase}/autonomous/approvals/pending`,
      );
      if (result.error) {
        throw new Error(result.error);
      }
      setRequests(result.data?.pending ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch approvals');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchRequests();
  }, [fetchRequests]);

  const handleApprove = async (requestId: string) => {
    try {
      setActionLoading(requestId);
      await apiFetch(`${apiBase}/autonomous/approvals/${requestId}/approve`, {
        method: 'POST',
        body: JSON.stringify({ approved_by: 'dashboard_user' }),
      });
      await fetchRequests();
      setSelectedRequest(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to approve');
    } finally {
      setActionLoading(null);
    }
  };

  const handleReject = async (requestId: string, reason: string) => {
    try {
      setActionLoading(requestId);
      await apiFetch(`${apiBase}/autonomous/approvals/${requestId}/reject`, {
        method: 'POST',
        body: JSON.stringify({ rejected_by: 'dashboard_user', reason }),
      });
      await fetchRequests();
      setSelectedRequest(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reject');
    } finally {
      setActionLoading(null);
    }
  };

  if (loading && requests.length === 0) {
    return <div className="text-white/50 animate-pulse">Loading approvals...</div>;
  }

  if (error) {
    return (
      <div className="p-4 bg-red-500/10 border border-red-500/30 rounded text-red-400">
        {error}
        <button onClick={fetchRequests} className="ml-4 text-sm underline">
          Retry
        </button>
      </div>
    );
  }

  if (requests.length === 0) {
    return (
      <div className="text-center py-12 text-white/50">
        <div className="text-4xl mb-2">✓</div>
        <div>No pending approvals</div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-white/70">
          {requests.length} pending approval{requests.length !== 1 ? 's' : ''}
        </span>
        <button
          onClick={fetchRequests}
          disabled={loading}
          aria-label="Refresh approval requests"
          className="text-xs text-white/50 hover:text-white"
        >
          Refresh
        </button>
      </div>

      <div className="space-y-2">
        {requests.map((request) => {
          const riskStyle = RISK_COLORS[request.risk_level] ?? RISK_COLORS.medium;
          const isSelected = selectedRequest?.id === request.id;

          return (
            <div
              key={request.id}
              className={`border rounded-lg transition-colors ${
                isSelected ? 'border-[var(--accent)]/50 bg-white/10' : 'border-white/10 bg-white/5'
              }`}
            >
              <button
                onClick={() => setSelectedRequest(isSelected ? null : request)}
                aria-expanded={isSelected}
                aria-label={`${isSelected ? 'Collapse' : 'Expand'} approval request: ${request.title}`}
                className="w-full p-4 text-left"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-white truncate">{request.title}</div>
                    <div className="text-sm text-white/50 mt-1 line-clamp-2">
                      {request.description}
                    </div>
                  </div>
                  <div className={`px-2 py-0.5 rounded text-xs ${riskStyle.bg} ${riskStyle.text}`}>
                    {request.risk_level}
                  </div>
                </div>
                <div className="flex items-center gap-4 mt-2 text-xs text-white/40">
                  <span>
                    {request.changes.length} file{request.changes.length !== 1 ? 's' : ''}
                  </span>
                  <span>{new Date(request.requested_at).toLocaleString()}</span>
                </div>
              </button>

              {isSelected && (
                <div className="border-t border-white/10 p-4 space-y-4">
                  {/* Changes list */}
                  <div>
                    <div className="text-xs font-medium text-white/70 mb-2">Changes</div>
                    <div className="space-y-1 max-h-40 overflow-y-auto">
                      {request.changes.map((change, i) => (
                        <div key={i} className="text-xs text-white/50 font-theme-data">
                          <span
                            className={
                              change.action === 'create'
                                ? 'text-[var(--accent)]'
                                : change.action === 'delete'
                                  ? 'text-red-400'
                                  : 'text-yellow-500'
                            }
                          >
                            {change.action === 'create'
                              ? '+'
                              : change.action === 'delete'
                                ? '-'
                                : '~'}
                          </span>{' '}
                          {change.file}
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleApprove(request.id)}
                      disabled={actionLoading === request.id}
                      aria-label={`Approve request: ${request.title}`}
                      className="flex-1 px-4 py-2 bg-[var(--accent)]/20 hover:bg-[var(--accent)]/30 text-[var(--accent)] rounded transition-colors disabled:opacity-50"
                    >
                      {actionLoading === request.id ? '...' : 'Approve'}
                    </button>
                    <button
                      onClick={() => handleReject(request.id, 'Rejected via dashboard')}
                      disabled={actionLoading === request.id}
                      aria-label={`Reject request: ${request.title}`}
                      className="flex-1 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded transition-colors disabled:opacity-50"
                    >
                      {actionLoading === request.id ? '...' : 'Reject'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default ApprovalPanel;
