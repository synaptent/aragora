'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '@/config';
import { useAuth } from '@/context/AuthContext';

interface FollowUpItem {
  followup_id: string;
  email_id: string;
  thread_id: string;
  subject: string;
  recipient: string;
  sent_at: string;
  expected_by: string | null;
  status: 'awaiting' | 'overdue' | 'received' | 'resolved';
  days_waiting: number;
  urgency_score: number;
  reminder_count: number;
}

interface FollowUpPanelProps {
  apiBase?: string;
  userId?: string;
  authToken?: string;
  onEmailSelect?: (emailId: string) => void;
  onRefresh?: () => void;
  className?: string;
}

export function FollowUpPanel({
  userId: _userId = 'default',
  apiBase: apiBaseProp,
  onEmailSelect,
  onRefresh,
  className = '',
}: FollowUpPanelProps) {
  const { isAuthenticated, isLoading: authLoading, tokens } = useAuth();
  const apiBase = apiBaseProp ?? API_BASE_URL;
  const [followups, setFollowups] = useState<FollowUpItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolving, setResolving] = useState<string | null>(null);
  const [showResolved, setShowResolved] = useState(false);

  const getAuthHeaders = useCallback((): HeadersInit => {
    const headers: HeadersInit = { 'Content-Type': 'application/json' };
    if (tokens?.access_token) {
      headers['Authorization'] = `Bearer ${tokens.access_token}`;
    }
    return headers;
  }, [tokens?.access_token]);

  const fetchFollowups = useCallback(async () => {
    // Skip if not authenticated
    if (!isAuthenticated || authLoading) {
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const params = new URLSearchParams({
        include_resolved: showResolved.toString(),
        sort_by: 'urgency',
      });
      const res = await fetch(`${apiBase}/api/v1/email/followups/pending?${params}`, {
        headers: getAuthHeaders(),
      });
      const data = await res.json();
      if (data.status === 'success') {
        setFollowups(data.data.followups);
      } else {
        setError(data.message || 'Failed to load follow-ups');
      }
    } catch {
      setError('Failed to connect to server');
    } finally {
      setLoading(false);
    }
  }, [apiBase, showResolved, isAuthenticated, authLoading, getAuthHeaders]);

  useEffect(() => {
    fetchFollowups();
  }, [fetchFollowups]);

  const handleResolve = async (followupId: string, status: string) => {
    if (!tokens?.access_token) return;

    try {
      setResolving(followupId);
      const res = await fetch(`${apiBase}/api/v1/email/followups/${followupId}/resolve`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ status }),
      });
      const data = await res.json();
      if (data.status === 'success') {
        await fetchFollowups();
        onRefresh?.();
      }
    } catch {
      setError('Failed to resolve follow-up');
    } finally {
      setResolving(null);
    }
  };

  const handleCheckReplies = async () => {
    if (!tokens?.access_token) return;

    try {
      setLoading(true);
      const res = await fetch(`${apiBase}/api/v1/email/followups/check-replies`, {
        method: 'POST',
        headers: getAuthHeaders(),
      });
      const data = await res.json();
      if (data.status === 'success' && data.data.replied.length > 0) {
        await fetchFollowups();
        onRefresh?.();
      }
    } catch {
      setError('Failed to check replies');
    } finally {
      setLoading(false);
    }
  };

  const handleAutoDetect = async () => {
    if (!tokens?.access_token) return;

    try {
      setLoading(true);
      const res = await fetch(`${apiBase}/api/v1/email/followups/auto-detect`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ days_back: 7 }),
      });
      const data = await res.json();
      if (data.status === 'success') {
        await fetchFollowups();
        onRefresh?.();
      }
    } catch {
      setError('Failed to auto-detect');
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'overdue':
        return 'text-red-400 bg-red-500/20';
      case 'awaiting':
        return 'text-yellow-400 bg-yellow-500/20';
      case 'received':
        return 'text-green-400 bg-green-500/20';
      case 'resolved':
        return 'text-gray-400 bg-gray-500/20';
      default:
        return 'text-gray-400 bg-gray-500/20';
    }
  };

  const getUrgencyIndicator = (days: number, status: string) => {
    if (status === 'overdue') return '!!!';
    if (days > 5) return '!!';
    if (days > 3) return '!';
    return '';
  };

  const overdueCount = followups.filter((f) => f.status === 'overdue').length;
  const awaitingCount = followups.filter((f) => f.status === 'awaiting').length;

  return (
    <div className={`bg-[var(--surface)] border border-[var(--border)] rounded ${className}`}>
      {/* Header */}
      <div className="p-4 border-b border-[var(--border)]">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <h3 className="font-theme-data text-sm font-medium text-[var(--text)]">
              Follow-Up Tracker
            </h3>
            {overdueCount > 0 && (
              <span className="px-2 py-0.5 text-xs rounded bg-red-500/20 text-red-400">
                {overdueCount} overdue
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleCheckReplies}
              disabled={loading}
              className="px-2 py-1 text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] rounded transition-colors"
            >
              Check Replies
            </button>
            <button
              onClick={handleAutoDetect}
              disabled={loading}
              className="px-2 py-1 text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] rounded transition-colors"
            >
              Auto-Detect
            </button>
          </div>
        </div>

        {/* Stats */}
        <div className="flex items-center gap-4 text-xs font-theme-data text-[var(--text-muted)]">
          <span>
            <span className="text-yellow-400">{awaitingCount}</span> awaiting
          </span>
          <span>
            <span className="text-red-400">{overdueCount}</span> overdue
          </span>
          <label className="flex items-center gap-1 ml-auto cursor-pointer">
            <input
              type="checkbox"
              checked={showResolved}
              onChange={(e) => setShowResolved(e.target.checked)}
              className="w-3 h-3"
            />
            Show resolved
          </label>
        </div>
      </div>

      {/* Content */}
      <div className="max-h-[400px] overflow-y-auto">
        {loading ? (
          <div className="p-8 text-center">
            <div className="text-[var(--text-muted)] text-sm font-theme-data">
              Loading follow-ups...
            </div>
          </div>
        ) : error ? (
          <div className="p-4 text-center">
            <div className="text-red-400 text-sm font-theme-data mb-2">{error}</div>
            <button
              onClick={fetchFollowups}
              className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--text)]"
            >
              Retry
            </button>
          </div>
        ) : followups.length === 0 ? (
          <div className="p-8 text-center">
            <div className="text-[var(--text-muted)] text-sm font-theme-data mb-2">
              No pending follow-ups
            </div>
            <button
              onClick={handleAutoDetect}
              className="text-xs font-theme-data text-blue-400 hover:text-blue-300"
            >
              Scan sent folder for unreplied emails
            </button>
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {followups.map((item) => (
              <div
                key={item.followup_id}
                className="p-3 hover:bg-[var(--surface-hover)] transition-colors"
              >
                <div className="flex items-start justify-between gap-2">
                  <div
                    className="flex-1 min-w-0 cursor-pointer"
                    onClick={() => onEmailSelect?.(item.email_id)}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className={`px-1.5 py-0.5 text-xs rounded font-theme-data ${getStatusColor(item.status)}`}
                      >
                        {item.status.toUpperCase()}
                      </span>
                      <span className="text-xs text-[var(--text-muted)] font-theme-data">
                        {item.days_waiting}d{getUrgencyIndicator(item.days_waiting, item.status)}
                      </span>
                      {item.reminder_count > 0 && (
                        <span className="text-xs text-[var(--text-muted)]">
                          ({item.reminder_count} reminders)
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-[var(--text)] truncate font-theme-data">
                      {item.subject}
                    </p>
                    <p className="text-xs text-[var(--text-muted)] truncate">
                      To: {item.recipient}
                    </p>
                  </div>

                  {/* Actions */}
                  {item.status !== 'resolved' && item.status !== 'received' && (
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => handleResolve(item.followup_id, 'received')}
                        disabled={resolving === item.followup_id}
                        className="px-2 py-1 text-xs font-theme-data text-green-400 hover:bg-green-500/20 rounded transition-colors"
                        title="Mark as replied"
                      >
                        Got Reply
                      </button>
                      <button
                        onClick={() => handleResolve(item.followup_id, 'no_longer_needed')}
                        disabled={resolving === item.followup_id}
                        className="px-2 py-1 text-xs font-theme-data text-[var(--text-muted)] hover:bg-[var(--surface-hover)] rounded transition-colors"
                        title="No longer needed"
                      >
                        Dismiss
                      </button>
                    </div>
                  )}
                </div>

                {/* Expected by */}
                {item.expected_by && item.status === 'awaiting' && (
                  <div className="mt-1 text-xs text-[var(--text-muted)]">
                    Expected by: {new Date(item.expected_by).toLocaleDateString()}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default FollowUpPanel;
