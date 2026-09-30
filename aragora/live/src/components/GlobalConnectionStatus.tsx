'use client';

import { useState, useEffect } from 'react';
import {
  useOptionalConnection,
  type OverallConnectionStatus,
  type ServiceConnection,
} from '@/context/ConnectionContext';

/**
 * Global connection status indicator that appears in the layout.
 *
 * Shows a minimal indicator when all services are connected,
 * and expands to show details when there are issues.
 *
 * Uses ConnectionContext to aggregate status from multiple WebSocket services.
 */

const STATUS_CONFIG: Record<
  OverallConnectionStatus,
  { color: string; bgColor: string; borderColor: string; label: string; icon: string }
> = {
  connected: {
    color: 'text-[var(--accent)]',
    bgColor: 'bg-[var(--accent)]/10',
    borderColor: 'border-[var(--accent)]/30',
    label: 'ALL SYSTEMS ONLINE',
    icon: '●',
  },
  partial: {
    color: 'text-[var(--acid-yellow)]',
    bgColor: 'bg-acid-yellow/10',
    borderColor: 'border-acid-yellow/30',
    label: 'PARTIAL CONNECTION',
    icon: '◐',
  },
  connecting: {
    color: 'text-[var(--acid-cyan)]',
    bgColor: 'bg-[var(--acid-cyan)]/10',
    borderColor: 'border-[var(--acid-cyan)]/30',
    label: 'CONNECTING...',
    icon: '◌',
  },
  disconnected: {
    color: 'text-text-muted',
    bgColor: 'bg-surface',
    borderColor: 'border-border',
    label: 'DISCONNECTED',
    icon: '○',
  },
  error: {
    color: 'text-[var(--crimson)]',
    bgColor: 'bg-[var(--crimson)]/10',
    borderColor: 'border-[var(--crimson)]/30',
    label: 'CONNECTION ERROR',
    icon: '✕',
  },
};

function formatRelativeTime(date: Date | null): string {
  if (!date) return 'Never';
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);

  if (diffSecs < 10) return 'Just now';
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return date.toLocaleDateString();
}

function getLatencyIndicator(service: ServiceConnection): { label: string; color: string } | null {
  if (!service.lastConnected) return null;

  // Calculate "freshness" of connection as a proxy for health
  const now = new Date();
  const diffMs = now.getTime() - service.lastConnected.getTime();

  // If connected within the last 5 seconds, consider it "fresh"
  if (diffMs < 5000) {
    return { label: 'FAST', color: 'text-[var(--accent)]' };
  }
  // Connected within last minute
  if (diffMs < 60000) {
    return { label: 'OK', color: 'text-[var(--accent)]' };
  }
  // Connected within last 5 minutes
  if (diffMs < 300000) {
    return { label: 'SLOW', color: 'text-[var(--acid-yellow)]' };
  }
  // Stale connection
  return { label: 'STALE', color: 'text-[var(--acid-yellow)]' };
}

export function GlobalConnectionStatus() {
  const connection = useOptionalConnection();
  const [isExpanded, setIsExpanded] = useState(false);
  const [, setTick] = useState(0);

  // Update relative times every 10 seconds
  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 10000);
    return () => clearInterval(interval);
  }, []);

  // Don't render if outside provider or no services registered
  if (!connection || connection.totalServices === 0) {
    return null;
  }

  const {
    overallStatus,
    services,
    connectedCount,
    totalServices,
    isReconnecting,
    lastAllConnected,
    reconnectAll,
    requestReconnect,
  } = connection;
  const config = STATUS_CONFIG[overallStatus];

  // Only show expanded view for non-connected states by default
  const shouldShowDetails = overallStatus !== 'connected' || isExpanded;

  // Count disconnected services for retry all
  const disconnectedServices = Array.from(services.values()).filter(
    (s) => s.status !== 'connected' && s.status !== 'streaming',
  );

  return (
    <div className="fixed bottom-4 right-4 z-50 font-theme-data text-xs">
      {/* Minimal indicator for connected state */}
      {overallStatus === 'connected' && !isExpanded && (
        <button
          onClick={() => setIsExpanded(true)}
          className={`flex items-center gap-2 px-3 py-1.5 ${config.bgColor} border ${config.borderColor} rounded-full ${config.color} hover:opacity-80 transition-opacity`}
          title="Click for connection details"
        >
          <span className="animate-pulse">{config.icon}</span>
          <span>
            {connectedCount}/{totalServices}
          </span>
        </button>
      )}

      {/* Expanded view */}
      {shouldShowDetails && (
        <div
          className={`${config.bgColor} border ${config.borderColor} rounded-lg shadow-lg overflow-hidden min-w-[280px]`}
        >
          {/* Header */}
          <div
            className={`flex items-center justify-between px-3 py-2 border-b ${config.borderColor} cursor-pointer`}
            onClick={() => overallStatus === 'connected' && setIsExpanded(false)}
          >
            <div className={`flex items-center gap-2 ${config.color}`}>
              <span
                className={
                  overallStatus === 'connecting' || isReconnecting
                    ? 'animate-spin'
                    : 'animate-pulse'
                }
              >
                {config.icon}
              </span>
              <span>{config.label}</span>
            </div>
            <span className="text-text-muted">
              {connectedCount}/{totalServices}
            </span>
          </div>

          {/* Last All Connected Time */}
          {lastAllConnected && overallStatus !== 'connected' && (
            <div className="px-3 py-1.5 border-b border-border/50 text-text-muted text-[10px] flex items-center justify-between">
              <span>Last fully connected:</span>
              <span className="text-text">{formatRelativeTime(lastAllConnected)}</span>
            </div>
          )}

          {/* Service list */}
          <div className="px-3 py-2 space-y-1.5 max-h-[200px] overflow-y-auto">
            {Array.from(services.values()).map((service) => {
              const isConnected = service.status === 'connected' || service.status === 'streaming';
              const hasError = service.status === 'error';
              const isConnecting = service.status === 'connecting';
              const latency = isConnected ? getLatencyIndicator(service) : null;

              return (
                <div key={service.name} className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${
                        isConnected
                          ? 'bg-[var(--accent)]'
                          : hasError
                            ? 'bg-[var(--crimson)]'
                            : isConnecting
                              ? 'bg-[var(--acid-cyan)] animate-pulse'
                              : 'bg-text-muted'
                      }`}
                    />
                    <span className="text-text">{service.displayName}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {/* Latency/Quality indicator for connected services */}
                    {latency && (
                      <span className={`text-[10px] ${latency.color}`}>{latency.label}</span>
                    )}
                    {/* Reconnect attempt indicator */}
                    {service.reconnectAttempt > 0 && (
                      <span className="text-[var(--acid-yellow)] text-[10px]">
                        retry #{service.reconnectAttempt}
                      </span>
                    )}
                    {/* Error message */}
                    {hasError && service.error && (
                      <span
                        className="text-[var(--crimson)] text-[10px] truncate max-w-[100px]"
                        title={service.error}
                      >
                        {service.error}
                      </span>
                    )}
                    {/* Connected OK indicator */}
                    {isConnected && !latency && (
                      <span className="text-[var(--accent)] text-[10px]">OK</span>
                    )}
                    {/* Individual retry button for disconnected services */}
                    {!isConnected && !isConnecting && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          requestReconnect(service.name);
                        }}
                        className="text-[10px] text-[var(--acid-cyan)] hover:text-[var(--acid-cyan)]/80 transition-colors"
                        title={`Retry ${service.displayName}`}
                      >
                        Retry
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Reconnecting indicator */}
          {isReconnecting && (
            <div className="px-3 py-1.5 border-t border-border text-[var(--acid-yellow)] text-center">
              Attempting to reconnect...
            </div>
          )}

          {/* Action buttons */}
          <div className="flex border-t border-border">
            {/* Retry All button - only show when there are disconnected services */}
            {disconnectedServices.length > 0 && !isReconnecting && (
              <button
                onClick={reconnectAll}
                className="flex-1 px-3 py-2 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 text-center transition-colors border-r border-border"
              >
                Retry All ({disconnectedServices.length})
              </button>
            )}

            {/* Close button for expanded connected state */}
            {overallStatus === 'connected' && isExpanded && (
              <button
                onClick={() => setIsExpanded(false)}
                className="flex-1 px-3 py-2 text-text-muted hover:text-text text-center transition-colors"
              >
                Collapse
              </button>
            )}

            {/* Connection info for non-connected states */}
            {overallStatus !== 'connected' && disconnectedServices.length === 0 && (
              <div className="flex-1 px-3 py-2 text-text-muted text-center">Connecting...</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default GlobalConnectionStatus;
