'use client';

import { useState, useCallback, useEffect } from 'react';
import type { ChannelType } from './ChannelSelector';
import { useAuth } from '@/context/AuthContext';

export interface DeliveryRecord {
  id: string;
  receiptId: string;
  channel: ChannelType;
  destination: string;
  destinationName?: string;
  deliveredAt: string;
  status: 'success' | 'failed' | 'pending';
  errorMessage?: string;
  deliveredBy?: string;
}

export interface DeliveryHistoryProps {
  /** Receipt ID to filter by (optional) */
  receiptId?: string;
  /** API base URL */
  apiUrl: string;
  /** Maximum items to show */
  limit?: number;
  /** Show compact view */
  compact?: boolean;
}

// Demo data
const DEMO_HISTORY: DeliveryRecord[] = [
  {
    id: 'del-1',
    receiptId: 'rcpt-abc123',
    channel: 'slack',
    destination: 'C01234567',
    destinationName: '#security-alerts',
    deliveredAt: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    status: 'success',
    deliveredBy: 'admin@example.com',
  },
  {
    id: 'del-2',
    receiptId: 'rcpt-def456',
    channel: 'email',
    destination: 'compliance@example.com',
    destinationName: 'compliance@example.com',
    deliveredAt: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
    status: 'success',
    deliveredBy: 'admin@example.com',
  },
  {
    id: 'del-3',
    receiptId: 'rcpt-ghi789',
    channel: 'teams',
    destination: 'T01234567',
    destinationName: 'Security Team',
    deliveredAt: new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString(),
    status: 'failed',
    errorMessage: 'Channel not found',
    deliveredBy: 'user@example.com',
  },
];

const CHANNEL_ICONS: Record<ChannelType, string> = {
  slack: '?',
  teams: '?',
  discord: '?',
  email: '?',
};

/**
 * Shows delivery history for receipts.
 */
export function DeliveryHistory({
  receiptId,
  apiUrl,
  limit = 10,
  compact = false,
}: DeliveryHistoryProps) {
  const { isAuthenticated, isLoading: authLoading, tokens } = useAuth();
  const [history, setHistory] = useState<DeliveryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchHistory = useCallback(async () => {
    // Skip if not authenticated - use demo data
    if (!isAuthenticated || authLoading) {
      setHistory(receiptId ? DEMO_HISTORY.filter((h) => h.receiptId === receiptId) : DEMO_HISTORY);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams();
      params.append('limit', limit.toString());
      if (receiptId) {
        params.append('receipt_id', receiptId);
      }

      const headers: HeadersInit = { 'Content-Type': 'application/json' };
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }
      const response = await fetch(`${apiUrl}/api/v1/receipts/deliveries?${params}`, { headers });

      if (!response.ok) {
        // Use demo data on error
        setHistory(
          receiptId ? DEMO_HISTORY.filter((h) => h.receiptId === receiptId) : DEMO_HISTORY,
        );
        return;
      }

      const data = await response.json();
      setHistory(data.deliveries || []);
    } catch {
      // Use demo data on error
      setHistory(receiptId ? DEMO_HISTORY.filter((h) => h.receiptId === receiptId) : DEMO_HISTORY);
    } finally {
      setLoading(false);
    }
  }, [apiUrl, receiptId, limit, isAuthenticated, authLoading, tokens?.access_token]);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  if (loading) {
    return (
      <div className="space-y-2 animate-pulse">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-12 bg-surface rounded" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-500/10 border border-red-500/30 rounded text-sm text-red-400">
        {error}
      </div>
    );
  }

  if (history.length === 0) {
    return (
      <div className="p-6 text-center text-text-muted">
        <div className="text-3xl mb-2">?</div>
        <p className="text-sm">No deliveries yet</p>
      </div>
    );
  }

  if (compact) {
    return (
      <div className="space-y-1">
        {history.map((record) => (
          <div key={record.id} className="flex items-center gap-2 p-2 text-xs">
            <span>{CHANNEL_ICONS[record.channel]}</span>
            <span className="text-text-muted">{record.destinationName}</span>
            <span
              className={`ml-auto ${
                record.status === 'success'
                  ? 'text-green-400'
                  : record.status === 'failed'
                    ? 'text-red-400'
                    : 'text-yellow-400'
              }`}
            >
              {record.status}
            </span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {history.map((record) => (
        <DeliveryRecordItem key={record.id} record={record} />
      ))}
    </div>
  );
}

interface DeliveryRecordItemProps {
  record: DeliveryRecord;
}

function DeliveryRecordItem({ record }: DeliveryRecordItemProps) {
  const statusColors = {
    success: 'text-green-400 bg-green-500/10',
    failed: 'text-red-400 bg-red-500/10',
    pending: 'text-yellow-400 bg-yellow-500/10',
  };

  const timeFormatted = formatTimeAgo(new Date(record.deliveredAt));

  return (
    <div className="p-3 bg-surface rounded-lg border border-border">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xl">{CHANNEL_ICONS[record.channel]}</span>
          <div>
            <div className="font-theme-data text-sm">
              {record.destinationName || record.destination}
            </div>
            <div className="text-xs text-text-muted">
              Receipt: {record.receiptId.substring(0, 12)}...
            </div>
          </div>
        </div>
        <div className="text-right">
          <span
            className={`px-2 py-0.5 text-xs font-theme-data rounded ${statusColors[record.status]}`}
          >
            {record.status}
          </span>
          <div className="text-xs text-text-muted mt-1">{timeFormatted}</div>
        </div>
      </div>

      {record.errorMessage && (
        <div className="mt-2 p-2 bg-red-500/10 rounded text-xs text-red-400">
          {record.errorMessage}
        </div>
      )}

      {record.deliveredBy && (
        <div className="mt-2 text-xs text-text-muted">Delivered by: {record.deliveredBy}</div>
      )}
    </div>
  );
}

function formatTimeAgo(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

export default DeliveryHistory;
