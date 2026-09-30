'use client';

import { useState, useCallback, useEffect, useMemo } from 'react';
import { PanelTemplate } from '@/components/shared/PanelTemplate';
import { useApi } from '@/hooks/useApi';
import { useBackend } from '@/components/BackendSelector';
import {
  ChannelCard,
  type OutboundChannel,
  type OutboundChannelType,
  type ChannelStatus,
} from './ChannelCard';
import { ChannelConfigModal } from './ChannelConfigModal';
import { DeliveryLog, type DeliveryLogEntry } from './DeliveryLog';
import { logger } from '@/utils/logger';

export type ChannelFilter = 'all' | 'active' | 'inactive' | 'error';
export type PanelTab = 'channels' | 'delivery-log' | 'analytics';

export interface OutboundChannelsPanelProps {
  /** Callback when a channel is selected */
  onSelectChannel?: (channel: OutboundChannel) => void;
  /** Enable real-time updates */
  enableRealtime?: boolean;
  /** Custom CSS classes */
  className?: string;
}

// Available outbound channel types
const AVAILABLE_CHANNELS: Omit<OutboundChannel, 'id' | 'status' | 'stats'>[] = [
  {
    type: 'slack',
    name: 'Slack',
    description: 'Deliver decisions to Slack channels and threads',
    enabled: false,
  },
  {
    type: 'teams',
    name: 'Microsoft Teams',
    description: 'Send decisions to Teams channels via webhooks',
    enabled: false,
  },
  {
    type: 'discord',
    name: 'Discord',
    description: 'Post decisions to Discord servers',
    enabled: false,
  },
  {
    type: 'telegram',
    name: 'Telegram',
    description: 'Send decisions to Telegram chats via bot',
    enabled: false,
  },
  {
    type: 'whatsapp',
    name: 'WhatsApp Business',
    description: 'Deliver decisions via WhatsApp Business API',
    enabled: false,
  },
  {
    type: 'voice',
    name: 'Voice Calls',
    description: 'Convert decisions to voice calls with TTS',
    enabled: false,
  },
  {
    type: 'email',
    name: 'Email',
    description: 'Send decisions via email with customizable templates',
    enabled: false,
  },
  {
    type: 'webhook',
    name: 'Custom Webhook',
    description: 'Deliver decisions to any HTTP endpoint',
    enabled: false,
  },
];

/**
 * Outbound Channels Panel for managing decision delivery channels.
 * Supports Slack, Teams, Discord, Telegram, WhatsApp, Voice, and custom webhooks.
 */
export function OutboundChannelsPanel({
  onSelectChannel,
  enableRealtime = true,
  className = '',
}: OutboundChannelsPanelProps) {
  const { config: backendConfig } = useBackend();
  const api = useApi(backendConfig?.api);

  // State
  const [channels, setChannels] = useState<OutboundChannel[]>([]);
  const [deliveryLog, setDeliveryLog] = useState<DeliveryLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<PanelTab>('channels');
  const [filter, setFilter] = useState<ChannelFilter>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedChannel, setSelectedChannel] = useState<OutboundChannel | null>(null);
  const [configModalOpen, setConfigModalOpen] = useState(false);

  // Merge available channels with configured channels
  const mergedChannels = useMemo(() => {
    const configured = new Map(channels.map((c) => [c.type, c]));

    return AVAILABLE_CHANNELS.map((available) => {
      const existing = configured.get(available.type as OutboundChannelType);
      if (existing) {
        return existing;
      }
      return { ...available, id: `${available.type}-new`, status: 'inactive' as ChannelStatus };
    });
  }, [channels]);

  // Filter channels
  const filteredChannels = useMemo(() => {
    let result = mergedChannels;

    // Apply search filter
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      result = result.filter(
        (c) =>
          c.name.toLowerCase().includes(query) ||
          c.type.toLowerCase().includes(query) ||
          c.description.toLowerCase().includes(query),
      );
    }

    // Apply status filter
    switch (filter) {
      case 'active':
        result = result.filter((c) => c.status === 'active');
        break;
      case 'inactive':
        result = result.filter((c) => c.status === 'inactive');
        break;
      case 'error':
        result = result.filter((c) => c.status === 'error' || c.status === 'rate_limited');
        break;
    }

    return result;
  }, [mergedChannels, filter, searchQuery]);

  // Load channels and delivery log
  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [channelsResponse, logResponse] = await Promise.all([
        api.get('/api/outbound-channels').catch(() => ({ channels: [] })) as Promise<{
          channels: OutboundChannel[];
        }>,
        api.get('/api/outbound-channels/delivery-log').catch(() => ({ entries: [] })) as Promise<{
          entries: DeliveryLogEntry[];
        }>,
      ]);

      setChannels(channelsResponse.channels || []);
      setDeliveryLog(logResponse.entries || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load channels');

      // Use mock data for demo
      setChannels([
        {
          id: 'slack-1',
          type: 'slack',
          name: 'Slack',
          description: 'Deliver decisions to Slack channels',
          enabled: true,
          status: 'active',
          default_thread: 'decisions',
          stats: {
            messages_sent_today: 47,
            messages_sent_total: 12453,
            success_rate: 99.7,
            avg_delivery_time_ms: 234,
            last_delivery: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
          },
        },
        {
          id: 'teams-1',
          type: 'teams',
          name: 'Microsoft Teams',
          description: 'Send decisions to Teams channels',
          enabled: true,
          status: 'active',
          default_thread: 'AI Decisions',
          stats: {
            messages_sent_today: 23,
            messages_sent_total: 5621,
            success_rate: 98.9,
            avg_delivery_time_ms: 456,
            last_delivery: new Date(Date.now() - 15 * 60 * 1000).toISOString(),
          },
        },
        {
          id: 'discord-1',
          type: 'discord',
          name: 'Discord',
          description: 'Post decisions to Discord servers',
          enabled: false,
          status: 'inactive',
        },
        {
          id: 'email-1',
          type: 'email',
          name: 'Email',
          description: 'Send decisions via email',
          enabled: true,
          status: 'error',
          error_message: 'SMTP authentication failed',
          stats: {
            messages_sent_today: 0,
            messages_sent_total: 3421,
            success_rate: 94.2,
            avg_delivery_time_ms: 1200,
            last_delivery: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
          },
        },
      ]);

      setDeliveryLog([
        {
          id: 'del-1',
          message_id: 'msg-abc123',
          channel_type: 'slack',
          channel_name: 'Slack',
          recipient: '#decisions',
          content_preview:
            'Consensus reached: Implement rate limiting with token bucket algorithm...',
          status: 'delivered',
          sent_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
          delivered_at: new Date(Date.now() - 5 * 60 * 1000 + 234).toISOString(),
          deliberation_id: 'deb-xyz789',
        },
        {
          id: 'del-2',
          message_id: 'msg-def456',
          channel_type: 'teams',
          channel_name: 'Teams',
          recipient: 'AI Decisions',
          content_preview: 'Decision pending approval: Architecture change for microservices...',
          status: 'sent',
          sent_at: new Date(Date.now() - 15 * 60 * 1000).toISOString(),
          deliberation_id: 'deb-abc123',
        },
        {
          id: 'del-3',
          message_id: 'msg-ghi789',
          channel_type: 'email',
          channel_name: 'Email',
          recipient: 'team@company.com',
          content_preview: 'Weekly debate summary...',
          status: 'failed',
          sent_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
          error_message: 'SMTP authentication failed',
          retry_count: 3,
        },
        {
          id: 'del-4',
          message_id: 'msg-jkl012',
          channel_type: 'slack',
          channel_name: 'Slack',
          recipient: '#engineering',
          content_preview: 'Code review consensus: Approve with minor changes...',
          status: 'delivered',
          sent_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
          delivered_at: new Date(Date.now() - 2 * 60 * 60 * 1000 + 189).toISOString(),
          deliberation_id: 'deb-def456',
        },
      ]);
    } finally {
      setLoading(false);
    }
  }, [api]);

  // Load on mount
  useEffect(() => {
    loadData();
  }, [loadData]);

  // Polling for real-time updates
  useEffect(() => {
    if (!enableRealtime) return;

    const interval = setInterval(() => {
      loadData();
    }, 15000);

    return () => clearInterval(interval);
  }, [enableRealtime, loadData]);

  // Handle channel selection
  const handleSelectChannel = useCallback(
    (channel: OutboundChannel) => {
      setSelectedChannel(channel);
      onSelectChannel?.(channel);
    },
    [onSelectChannel],
  );

  // Handle configure
  const handleConfigure = useCallback((channel: OutboundChannel) => {
    setSelectedChannel(channel);
    setConfigModalOpen(true);
  }, []);

  // Handle toggle
  const handleToggle = useCallback(
    async (channel: OutboundChannel, enabled: boolean) => {
      try {
        await api.put(`/api/outbound-channels/${channel.id}`, { enabled });
        loadData();
      } catch (err) {
        logger.error('Failed to toggle channel:', err);
        // Optimistic update fallback
        setChannels((prev) =>
          prev.map((c) =>
            c.id === channel.id ? { ...c, enabled, status: enabled ? 'active' : 'inactive' } : c,
          ),
        );
      }
    },
    [api, loadData],
  );

  // Handle test
  const handleTest = useCallback(
    async (channel: OutboundChannel) => {
      try {
        const result = (await api.post(`/api/outbound-channels/${channel.id}/test`)) as {
          success: boolean;
          message?: string;
        };
        if (result.success) {
          alert('Test message sent successfully!');
        } else {
          alert(`Test failed: ${result.message || 'Unknown error'}`);
        }
      } catch (err) {
        logger.error('Failed to test channel:', err);
        alert('Test failed. Please check your configuration.');
      }
    },
    [api],
  );

  // Handle save config
  const handleSaveConfig = useCallback(
    async (channelId: string, config: Record<string, unknown>) => {
      await api.put(`/api/outbound-channels/${channelId}`, { config });
      loadData();
    },
    [api, loadData],
  );

  // Handle test connection
  const handleTestConnection = useCallback(
    async (channelId: string, config: Record<string, unknown>) => {
      const result = (await api.post(`/api/outbound-channels/test`, {
        channel_id: channelId,
        config,
      })) as { success: boolean };
      return result.success;
    },
    [api],
  );

  // Handle retry delivery
  const handleRetryDelivery = useCallback(
    async (entry: DeliveryLogEntry) => {
      try {
        await api.post(`/api/outbound-channels/delivery/${entry.id}/retry`);
        loadData();
      } catch (err) {
        logger.error('Failed to retry delivery:', err);
      }
    },
    [api, loadData],
  );

  // Filter counts
  const filterCounts = useMemo(
    () => ({
      all: mergedChannels.length,
      active: mergedChannels.filter((c) => c.status === 'active').length,
      inactive: mergedChannels.filter((c) => c.status === 'inactive').length,
      error: mergedChannels.filter((c) => c.status === 'error' || c.status === 'rate_limited')
        .length,
    }),
    [mergedChannels],
  );

  // Summary stats
  const summaryStats = useMemo(() => {
    const activeChannels = channels.filter((c) => c.enabled);
    const totalSentToday = activeChannels.reduce(
      (sum, c) => sum + (c.stats?.messages_sent_today || 0),
      0,
    );
    const avgSuccessRate =
      activeChannels.length > 0
        ? activeChannels.reduce((sum, c) => sum + (c.stats?.success_rate || 0), 0) /
          activeChannels.length
        : 0;

    return {
      activeChannels: activeChannels.length,
      totalSentToday,
      avgSuccessRate: avgSuccessRate.toFixed(1),
      pendingDeliveries: deliveryLog.filter((e) => e.status === 'pending' || e.status === 'sent')
        .length,
    };
  }, [channels, deliveryLog]);

  const tabs = [
    { id: 'channels' as PanelTab, label: 'Channels' },
    { id: 'delivery-log' as PanelTab, label: 'Delivery Log' },
    { id: 'analytics' as PanelTab, label: 'Analytics' },
  ];

  return (
    <PanelTemplate
      title="Outbound Channels"
      icon="📤"
      loading={loading}
      error={error}
      onRefresh={loadData}
      className={className}
    >
      {/* Summary Stats */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        <div className="bg-surface rounded p-3 text-center">
          <div className="text-xl font-theme-data font-bold text-[var(--accent)]">
            {summaryStats.activeChannels}
          </div>
          <div className="text-xs text-text-muted">Active Channels</div>
        </div>
        <div className="bg-surface rounded p-3 text-center">
          <div className="text-xl font-theme-data font-bold text-cyan-400">
            {summaryStats.totalSentToday}
          </div>
          <div className="text-xs text-text-muted">Sent Today</div>
        </div>
        <div className="bg-surface rounded p-3 text-center">
          <div className="text-xl font-theme-data font-bold text-[var(--accent)]">
            {summaryStats.avgSuccessRate}%
          </div>
          <div className="text-xs text-text-muted">Success Rate</div>
        </div>
        <div className="bg-surface rounded p-3 text-center">
          <div className="text-xl font-theme-data font-bold text-yellow-400">
            {summaryStats.pendingDeliveries}
          </div>
          <div className="text-xs text-text-muted">Pending</div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 p-1 bg-surface rounded">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 px-4 py-2 text-sm font-theme-data rounded transition-colors ${
              activeTab === tab.id
                ? 'bg-[var(--accent)] text-bg'
                : 'text-text-muted hover:text-text'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Channels Tab */}
      {activeTab === 'channels' && (
        <>
          {/* Search and filters */}
          <div className="mb-4 space-y-3">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search channels..."
              className="w-full px-3 py-2 text-sm bg-surface border border-border rounded focus:border-[var(--accent)] focus:outline-none"
            />

            <div className="flex flex-wrap gap-1">
              {(['all', 'active', 'inactive', 'error'] as ChannelFilter[]).map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`px-3 py-1 text-xs font-theme-data rounded transition-colors ${
                    filter === f
                      ? 'bg-[var(--accent)] text-bg'
                      : 'bg-surface text-text-muted hover:text-text'
                  }`}
                >
                  {f.charAt(0).toUpperCase() + f.slice(1)} ({filterCounts[f]})
                </button>
              ))}
            </div>
          </div>

          {/* Channel grid */}
          <div className="grid gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
            {filteredChannels.map((channel) => (
              <ChannelCard
                key={channel.id}
                channel={channel}
                selected={selectedChannel?.id === channel.id}
                onSelect={handleSelectChannel}
                onConfigure={handleConfigure}
                onToggle={handleToggle}
                onTest={handleTest}
              />
            ))}
          </div>

          {filteredChannels.length === 0 && (
            <div className="text-center py-8">
              <div className="text-4xl mb-2">📭</div>
              <p className="text-text-muted">No channels found</p>
            </div>
          )}
        </>
      )}

      {/* Delivery Log Tab */}
      {activeTab === 'delivery-log' && (
        <DeliveryLog
          entries={deliveryLog}
          loading={loading}
          onRetry={handleRetryDelivery}
          onViewDetails={(entry) => {
            // Could open a modal with full details
            logger.debug('View delivery details:', entry);
          }}
        />
      )}

      {/* Analytics Tab */}
      {activeTab === 'analytics' && (
        <div className="card p-6 text-center">
          <div className="text-4xl mb-2">📊</div>
          <h3 className="font-theme-data text-lg mb-2">Delivery Analytics</h3>
          <p className="text-text-muted text-sm mb-4">
            Detailed analytics and reporting for outbound channel performance.
          </p>
          <div className="grid grid-cols-2 gap-4 mt-6">
            <div className="bg-surface rounded p-4">
              <div className="text-3xl font-theme-data font-bold text-[var(--accent)] mb-1">
                {channels
                  .reduce((sum, c) => sum + (c.stats?.messages_sent_total || 0), 0)
                  .toLocaleString()}
              </div>
              <div className="text-sm text-text-muted">Total Messages Sent</div>
            </div>
            <div className="bg-surface rounded p-4">
              <div className="text-3xl font-theme-data font-bold text-cyan-400 mb-1">
                {Math.round(
                  channels.reduce((sum, c) => sum + (c.stats?.avg_delivery_time_ms || 0), 0) /
                    Math.max(channels.filter((c) => c.stats).length, 1),
                )}
                ms
              </div>
              <div className="text-sm text-text-muted">Avg Delivery Time</div>
            </div>
          </div>
        </div>
      )}

      {/* Config Modal */}
      <ChannelConfigModal
        channel={selectedChannel}
        isOpen={configModalOpen}
        onClose={() => setConfigModalOpen(false)}
        onSave={handleSaveConfig}
        onTest={handleTestConnection}
      />
    </PanelTemplate>
  );
}

export default OutboundChannelsPanel;
