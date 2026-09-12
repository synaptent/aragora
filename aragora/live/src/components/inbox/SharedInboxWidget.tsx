'use client';

/**
 * SharedInboxWidget - Compact shared inbox status for dashboards
 */

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';

interface SharedInboxSummary {
  total_inboxes: number;
  total_messages: number;
  unread_count: number;
  assigned_to_me: number;
  urgent_count: number;
}

interface SharedInboxWidgetProps {
  apiBase?: string;
  authToken?: string;
  userId?: string;
  compact?: boolean;
  refreshInterval?: number;
}

export function SharedInboxWidget({
  apiBase,
  authToken,
  userId: _userId = 'me',
  compact = false,
  refreshInterval = 60000,
}: SharedInboxWidgetProps) {
  const [summary, setSummary] = useState<SharedInboxSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchSummary = useCallback(async () => {
    try {
      const baseUrl = apiBase || '';
      const response = await fetch(`${baseUrl}/api/v1/inbox/shared?workspace_id=default`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });

      if (response.ok) {
        const data = await response.json();
        const inboxes = data.inboxes || [];

        // Compute summary
        let totalMessages = 0;
        let unreadCount = 0;

        inboxes.forEach((inbox: { message_count?: number; unread_count?: number }) => {
          totalMessages += inbox.message_count || 0;
          unreadCount += inbox.unread_count || 0;
        });

        setSummary({
          total_inboxes: inboxes.length,
          total_messages: totalMessages,
          unread_count: unreadCount,
          assigned_to_me: 0, // Would need separate API call
          urgent_count: 0, // Would need separate API call
        });
      } else {
        // API error - show empty state
        setSummary(null);
      }
    } catch {
      // Network error - show empty state
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, [apiBase, authToken]);

  useEffect(() => {
    fetchSummary();
    const interval = setInterval(fetchSummary, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchSummary, refreshInterval]);

  if (compact) {
    return (
      <Link
        href="/shared-inbox"
        className="flex items-center gap-2 px-3 py-1.5 text-xs font-theme-data bg-[var(--surface)] border border-[var(--border)] rounded hover:border-[var(--acid-green)]/30 transition-colors"
      >
        <span>📬</span>
        <span className="text-[var(--text-muted)]">Shared</span>
        {summary && (
          <>
            {summary.unread_count > 0 && (
              <span className="text-[var(--acid-cyan)]">{summary.unread_count} new</span>
            )}
            {summary.urgent_count > 0 && (
              <span className="text-[var(--acid-red)]">{summary.urgent_count} urgent</span>
            )}
          </>
        )}
      </Link>
    );
  }

  if (loading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] p-4 rounded animate-pulse">
        <div className="h-4 bg-[var(--bg)] rounded w-1/3 mb-3" />
        <div className="h-12 bg-[var(--bg)] rounded" />
      </div>
    );
  }

  if (!summary) return null;

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded overflow-hidden">
      {/* Header */}
      <div className="p-3 border-b border-[var(--border)] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg">📬</span>
          <span className="text-sm font-theme-data text-[var(--acid-green)]">SHARED INBOXES</span>
        </div>
        <Link
          href="/shared-inbox"
          className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
        >
          Open →
        </Link>
      </div>

      {/* Stats */}
      <div className="p-3 grid grid-cols-3 gap-3">
        <div className="text-center">
          <div
            className={`text-xl font-theme-data font-bold ${
              summary.unread_count > 0 ? 'text-[var(--acid-cyan)]' : 'text-[var(--text)]'
            }`}
          >
            {summary.unread_count}
          </div>
          <div className="text-xs text-[var(--text-muted)]">Unread</div>
        </div>
        <div className="text-center">
          <div
            className={`text-xl font-theme-data font-bold ${
              summary.assigned_to_me > 0 ? 'text-[var(--acid-purple)]' : 'text-[var(--text)]'
            }`}
          >
            {summary.assigned_to_me}
          </div>
          <div className="text-xs text-[var(--text-muted)]">Assigned</div>
        </div>
        <div className="text-center">
          <div
            className={`text-xl font-theme-data font-bold ${
              summary.urgent_count > 0 ? 'text-[var(--acid-red)]' : 'text-[var(--text)]'
            }`}
          >
            {summary.urgent_count}
          </div>
          <div className="text-xs text-[var(--text-muted)]">Urgent</div>
        </div>
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-[var(--border)] bg-[var(--bg)]/50 flex items-center justify-between">
        <span className="text-xs text-[var(--text-muted)]">
          {summary.total_inboxes} inbox{summary.total_inboxes !== 1 ? 'es' : ''}
        </span>
        <span className="text-xs text-[var(--text-muted)]">{summary.total_messages} total</span>
      </div>
    </div>
  );
}

export default SharedInboxWidget;
