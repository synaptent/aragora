'use client';

import { useMemo } from 'react';

export type OutboundChannelType =
  'slack' | 'teams' | 'discord' | 'telegram' | 'whatsapp' | 'voice' | 'email' | 'webhook';
export type ChannelStatus = 'active' | 'inactive' | 'error' | 'rate_limited';

export interface ChannelStats {
  messages_sent_today: number;
  messages_sent_total: number;
  success_rate: number;
  avg_delivery_time_ms: number;
  last_delivery?: string;
}

export interface OutboundChannel {
  id: string;
  type: OutboundChannelType;
  name: string;
  description: string;
  enabled: boolean;
  status: ChannelStatus;
  default_thread?: string;
  webhook_url?: string;
  stats?: ChannelStats;
  error_message?: string;
  last_configured?: string;
}

export interface ChannelCardProps {
  channel: OutboundChannel;
  selected?: boolean;
  onSelect?: (channel: OutboundChannel) => void;
  onConfigure?: (channel: OutboundChannel) => void;
  onToggle?: (channel: OutboundChannel, enabled: boolean) => void;
  onTest?: (channel: OutboundChannel) => void;
}

const CHANNEL_ICONS: Record<OutboundChannelType, string> = {
  slack: '📢',
  teams: '👥',
  discord: '🎮',
  telegram: '✈️',
  whatsapp: '💬',
  voice: '🎙️',
  email: '📧',
  webhook: '🔗',
};

const CHANNEL_COLORS: Record<OutboundChannelType, string> = {
  slack: '#4A154B',
  teams: '#6264A7',
  discord: '#5865F2',
  telegram: '#0088cc',
  whatsapp: '#25D366',
  voice: '#FF6B6B',
  email: '#EA4335',
  webhook: '#6366F1',
};

function getStatusColor(status: ChannelStatus): string {
  switch (status) {
    case 'active':
      return 'text-[var(--accent)]';
    case 'inactive':
      return 'text-text-muted';
    case 'error':
      return 'text-red-400';
    case 'rate_limited':
      return 'text-yellow-400';
    default:
      return 'text-text-muted';
  }
}

function getStatusLabel(status: ChannelStatus): string {
  switch (status) {
    case 'active':
      return 'ACTIVE';
    case 'inactive':
      return 'INACTIVE';
    case 'error':
      return 'ERROR';
    case 'rate_limited':
      return 'RATE LIMITED';
    default:
      return (status as string).toUpperCase();
  }
}

function formatNumber(n: number): string {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return n.toString();
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
  return `${Math.floor(diffMins / 1440)}d ago`;
}

/**
 * Card component for displaying an outbound delivery channel.
 */
export function ChannelCard({
  channel,
  selected = false,
  onSelect,
  onConfigure,
  onToggle,
  onTest,
}: ChannelCardProps) {
  const icon = CHANNEL_ICONS[channel.type] || '📡';
  const color = CHANNEL_COLORS[channel.type] || '#6366F1';

  const successRateColor = useMemo(() => {
    if (!channel.stats) return 'text-text-muted';
    const rate = channel.stats.success_rate;
    if (rate >= 99) return 'text-[var(--accent)]';
    if (rate >= 95) return 'text-yellow-400';
    return 'text-red-400';
  }, [channel.stats]);

  return (
    <div
      onClick={() => onSelect?.(channel)}
      className={`card p-4 cursor-pointer transition-all duration-200 ${
        selected ? 'ring-2 ring-acid-green' : 'hover:border-[var(--accent)]/50'
      } ${!channel.enabled ? 'opacity-60' : ''}`}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center text-xl"
            style={{ backgroundColor: `${color}20` }}
          >
            {icon}
          </div>
          <div>
            <h3 className="font-theme-data font-bold text-sm">{channel.name}</h3>
            <span className={`text-xs font-theme-data ${getStatusColor(channel.status)}`}>
              ● {getStatusLabel(channel.status)}
            </span>
          </div>
        </div>

        {/* Toggle */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            onToggle?.(channel, !channel.enabled);
          }}
          className={`relative w-10 h-5 rounded-full transition-colors ${
            channel.enabled ? 'bg-[var(--accent)]' : 'bg-surface-alt'
          }`}
        >
          <span
            className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
              channel.enabled ? 'left-5' : 'left-0.5'
            }`}
          />
        </button>
      </div>

      {/* Description */}
      <p className="text-xs text-text-muted mb-3 line-clamp-2">{channel.description}</p>

      {/* Default Thread */}
      {channel.default_thread && (
        <div className="text-xs text-text-muted mb-3">
          <span className="text-cyan-400">Default:</span> #{channel.default_thread}
        </div>
      )}

      {/* Error Message */}
      {channel.status === 'error' && channel.error_message && (
        <div className="text-xs text-red-400 mb-3 p-2 bg-red-400/10 rounded">
          ⚠ {channel.error_message}
        </div>
      )}

      {/* Stats */}
      {channel.stats && (
        <div className="grid grid-cols-3 gap-2 mb-3 text-center">
          <div className="bg-surface rounded p-2">
            <div className="text-lg font-theme-data font-bold text-[var(--accent)]">
              {formatNumber(channel.stats.messages_sent_today)}
            </div>
            <div className="text-xs text-text-muted">Today</div>
          </div>
          <div className="bg-surface rounded p-2">
            <div className={`text-lg font-theme-data font-bold ${successRateColor}`}>
              {channel.stats.success_rate.toFixed(1)}%
            </div>
            <div className="text-xs text-text-muted">Success</div>
          </div>
          <div className="bg-surface rounded p-2">
            <div className="text-lg font-theme-data font-bold text-cyan-400">
              {channel.stats.avg_delivery_time_ms}ms
            </div>
            <div className="text-xs text-text-muted">Avg Time</div>
          </div>
        </div>
      )}

      {/* Last Delivery */}
      {channel.stats?.last_delivery && (
        <div className="text-xs text-text-muted mb-3">
          Last delivery: {formatTime(channel.stats.last_delivery)}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onConfigure?.(channel);
          }}
          className="flex-1 px-3 py-1.5 text-xs font-theme-data bg-surface hover:bg-surface-alt rounded transition-colors"
        >
          Configure
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onTest?.(channel);
          }}
          className="flex-1 px-3 py-1.5 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] hover:bg-[var(--accent)]/30 rounded transition-colors"
          disabled={!channel.enabled}
        >
          Test
        </button>
      </div>
    </div>
  );
}

export default ChannelCard;
