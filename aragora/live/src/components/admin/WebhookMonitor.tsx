'use client';

import { useState, useEffect, useCallback } from 'react';

interface Webhook {
  id: string;
  url: string;
  event_types: string[];
  enabled: boolean;
  description: string | null;
  failure_count: number;
  last_triggered_at: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_failure_reason: string | null;
  created_at: string;
}

interface DeliveryReceipt {
  id: string;
  webhook_id: string;
  event_type: string;
  event_id: string;
  delivery_status: 'pending' | 'delivered' | 'failed';
  http_status: number | null;
  attempt_count: number;
  latency_ms: number | null;
  error_message: string | null;
  delivered_at: string | null;
  created_at: string;
}

interface WebhookStats {
  total_webhooks: number;
  active_webhooks: number;
  total_deliveries: number;
  successful_deliveries: number;
  failed_deliveries: number;
  avg_latency_ms: number;
}

interface WebhookMonitorProps {
  apiBase?: string;
}

const STATUS_COLORS: Record<string, string> = {
  delivered: 'text-[var(--accent)] border-[var(--accent)]/30 bg-[var(--accent)]/10',
  pending: 'text-gold border-gold/30 bg-gold/10',
  failed: 'text-[var(--crimson)] border-[var(--crimson)]/30 bg-[var(--crimson)]/10',
};

export function WebhookMonitor({ apiBase = '/api' }: WebhookMonitorProps) {
  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [receipts, setReceipts] = useState<DeliveryReceipt[]>([]);
  const [, _setStats] = useState<WebhookStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedWebhook, setSelectedWebhook] = useState<Webhook | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('all');

  const fetchWebhooks = useCallback(async () => {
    try {
      const response = await fetch(`${apiBase}/webhooks`);
      if (!response.ok) throw new Error('Failed to fetch webhooks');
      const data = await response.json();
      setWebhooks(data.webhooks || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  }, [apiBase]);

  const fetchReceipts = useCallback(
    async (webhookId: string) => {
      try {
        const params = new URLSearchParams({ limit: '50' });
        if (statusFilter !== 'all') {
          params.set('status', statusFilter);
        }
        const response = await fetch(`${apiBase}/webhooks/${webhookId}/receipts?${params}`);
        if (!response.ok) throw new Error('Failed to fetch receipts');
        const data = await response.json();
        setReceipts(data.receipts || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      }
    },
    [apiBase, statusFilter],
  );

  const testWebhook = async (webhookId: string) => {
    try {
      const response = await fetch(`${apiBase}/webhooks/${webhookId}/test`, { method: 'POST' });
      if (!response.ok) throw new Error('Test delivery failed');
      const result = await response.json();
      alert(`Test delivery: ${result.success ? 'Success' : 'Failed'}`);
      fetchWebhooks();
    } catch (err) {
      alert(`Error: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  const toggleWebhook = async (webhook: Webhook) => {
    try {
      const response = await fetch(`${apiBase}/webhooks/${webhook.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !webhook.enabled }),
      });
      if (!response.ok) throw new Error('Failed to update webhook');
      fetchWebhooks();
    } catch (err) {
      alert(`Error: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  useEffect(() => {
    setLoading(true);
    fetchWebhooks().finally(() => setLoading(false));
  }, [fetchWebhooks]);

  useEffect(() => {
    if (selectedWebhook) {
      fetchReceipts(selectedWebhook.id);
    }
  }, [selectedWebhook, fetchReceipts]);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="animate-pulse text-[var(--acid-cyan)]">Loading webhooks...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 rounded-lg text-[var(--crimson)]">
        Error: {error}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-white">Webhook Monitor</h2>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-400">
            {webhooks.filter((w) => w.enabled).length} active / {webhooks.length} total
          </span>
          <button
            onClick={() => fetchWebhooks()}
            className="px-3 py-1.5 bg-[var(--acid-cyan)]/10 border border-[var(--acid-cyan)]/30 rounded text-[var(--acid-cyan)] text-sm hover:bg-[var(--acid-cyan)]/20"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Webhooks List */}
      <div className="bg-black/50 border border-white/10 rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-white/5">
            <tr>
              <th className="px-4 py-3 text-left text-sm text-gray-400">URL</th>
              <th className="px-4 py-3 text-left text-sm text-gray-400">Events</th>
              <th className="px-4 py-3 text-left text-sm text-gray-400">Status</th>
              <th className="px-4 py-3 text-left text-sm text-gray-400">Failures</th>
              <th className="px-4 py-3 text-left text-sm text-gray-400">Last Delivery</th>
              <th className="px-4 py-3 text-right text-sm text-gray-400">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {webhooks.map((webhook) => (
              <tr
                key={webhook.id}
                className={`hover:bg-white/5 cursor-pointer ${
                  selectedWebhook?.id === webhook.id ? 'bg-[var(--acid-cyan)]/10' : ''
                }`}
                onClick={() => setSelectedWebhook(webhook)}
              >
                <td className="px-4 py-3">
                  <div className="font-theme-data text-sm text-white truncate max-w-xs">
                    {webhook.url}
                  </div>
                  {webhook.description && (
                    <div className="text-xs text-gray-500 mt-0.5">{webhook.description}</div>
                  )}
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {webhook.event_types.slice(0, 2).map((event) => (
                      <span
                        key={event}
                        className="px-2 py-0.5 bg-purple/10 border border-purple/30 rounded text-xs text-purple"
                      >
                        {event}
                      </span>
                    ))}
                    {webhook.event_types.length > 2 && (
                      <span className="text-xs text-gray-500">
                        +{webhook.event_types.length - 2}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`px-2 py-0.5 rounded text-xs ${
                      webhook.enabled
                        ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
                        : 'bg-gray-500/10 text-gray-500'
                    }`}
                  >
                    {webhook.enabled ? 'Active' : 'Disabled'}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`text-sm ${
                      webhook.failure_count > 0 ? 'text-[var(--crimson)]' : 'text-gray-400'
                    }`}
                  >
                    {webhook.failure_count}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-400">
                  {webhook.last_triggered_at
                    ? new Date(webhook.last_triggered_at).toLocaleString()
                    : 'Never'}
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        testWebhook(webhook.id);
                      }}
                      className="px-2 py-1 text-xs bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] rounded hover:bg-[var(--acid-cyan)]/20"
                    >
                      Test
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleWebhook(webhook);
                      }}
                      className={`px-2 py-1 text-xs rounded ${
                        webhook.enabled
                          ? 'bg-[var(--crimson)]/10 text-[var(--crimson)] hover:bg-[var(--crimson)]/20'
                          : 'bg-[var(--accent)]/10 text-[var(--accent)] hover:bg-[var(--accent)]/20'
                      }`}
                    >
                      {webhook.enabled ? 'Disable' : 'Enable'}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Delivery Receipts Panel */}
      {selectedWebhook && (
        <div className="bg-black/50 border border-white/10 rounded-lg p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium text-white">
              Delivery History: {selectedWebhook.url}
            </h3>
            <div className="flex items-center gap-2">
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="bg-black/50 border border-white/20 rounded px-2 py-1 text-sm text-white"
              >
                <option value="all">All Status</option>
                <option value="delivered">Delivered</option>
                <option value="pending">Pending</option>
                <option value="failed">Failed</option>
              </select>
              <button
                onClick={() => setSelectedWebhook(null)}
                className="text-gray-400 hover:text-white"
              >
                Close
              </button>
            </div>
          </div>

          <div className="space-y-2 max-h-64 overflow-y-auto">
            {receipts.length === 0 ? (
              <div className="text-center py-8 text-gray-500">No delivery receipts found</div>
            ) : (
              receipts.map((receipt) => (
                <div
                  key={receipt.id}
                  className="flex items-center justify-between p-3 bg-white/5 rounded"
                >
                  <div className="flex items-center gap-4">
                    <span
                      className={`px-2 py-0.5 rounded text-xs ${
                        STATUS_COLORS[receipt.delivery_status]
                      }`}
                    >
                      {receipt.delivery_status}
                    </span>
                    <span className="text-sm text-white">{receipt.event_type}</span>
                    {receipt.http_status && (
                      <span className="text-xs text-gray-400">HTTP {receipt.http_status}</span>
                    )}
                    {receipt.latency_ms && (
                      <span className="text-xs text-gray-400">
                        {receipt.latency_ms.toFixed(0)}ms
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-gray-500">
                    {new Date(receipt.created_at).toLocaleString()}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
