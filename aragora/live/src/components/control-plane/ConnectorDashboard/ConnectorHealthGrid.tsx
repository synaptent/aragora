'use client';

import { useMemo } from 'react';
import type { ConnectorInfo, ConnectorStatus } from './ConnectorCard';

export interface ConnectorHealthData {
  connectorId: string;
  connectorName: string;
  connectorType: string;
  status: ConnectorStatus;
  uptime: number; // percentage (0-100)
  lastSync: string | null;
  errorRate: number; // percentage (0-100)
  avgSyncDuration: number; // seconds
  itemsSynced: number;
  health: 'healthy' | 'degraded' | 'unhealthy';
}

export interface ConnectorHealthGridProps {
  /** Connector health data */
  connectors: ConnectorHealthData[];
  /** Loading state */
  loading?: boolean;
  /** Callback when connector is clicked */
  onConnectorClick?: (connectorId: string) => void;
}

/**
 * Grid visualization showing health status of all connectors.
 */
export function ConnectorHealthGrid({
  connectors,
  loading = false,
  onConnectorClick,
}: ConnectorHealthGridProps) {
  const healthSummary = useMemo(() => {
    const healthy = connectors.filter((c) => c.health === 'healthy').length;
    const degraded = connectors.filter((c) => c.health === 'degraded').length;
    const unhealthy = connectors.filter((c) => c.health === 'unhealthy').length;
    const total = connectors.length;

    return {
      healthy,
      degraded,
      unhealthy,
      total,
      healthScore: total > 0 ? Math.round((healthy / total) * 100) : 100,
    };
  }, [connectors]);

  if (loading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="grid grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-16 bg-surface-lighter rounded-lg" />
          ))}
        </div>
        <div className="grid grid-cols-3 gap-3">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-24 bg-surface-lighter rounded-lg" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary Stats */}
      <div className="grid grid-cols-4 gap-3">
        <div className="p-3 bg-surface rounded-lg border border-border">
          <div className="text-xs text-text-muted mb-1">Health Score</div>
          <div
            className={`text-2xl font-theme-data font-bold ${
              healthSummary.healthScore >= 80
                ? 'text-green-400'
                : healthSummary.healthScore >= 50
                  ? 'text-yellow-400'
                  : 'text-red-400'
            }`}
          >
            {healthSummary.healthScore}%
          </div>
        </div>
        <div className="p-3 bg-surface rounded-lg border border-green-500/30">
          <div className="text-xs text-text-muted mb-1">Healthy</div>
          <div className="text-2xl font-theme-data font-bold text-green-400">
            {healthSummary.healthy}
          </div>
        </div>
        <div className="p-3 bg-surface rounded-lg border border-yellow-500/30">
          <div className="text-xs text-text-muted mb-1">Degraded</div>
          <div className="text-2xl font-theme-data font-bold text-yellow-400">
            {healthSummary.degraded}
          </div>
        </div>
        <div className="p-3 bg-surface rounded-lg border border-red-500/30">
          <div className="text-xs text-text-muted mb-1">Unhealthy</div>
          <div className="text-2xl font-theme-data font-bold text-red-400">
            {healthSummary.unhealthy}
          </div>
        </div>
      </div>

      {/* Connector Health Grid */}
      <div className="grid grid-cols-3 gap-3">
        {connectors.map((connector) => (
          <ConnectorHealthCard
            key={connector.connectorId}
            connector={connector}
            onClick={() => onConnectorClick?.(connector.connectorId)}
          />
        ))}
      </div>

      {connectors.length === 0 && (
        <div className="text-center py-8 text-text-muted">No connectors configured</div>
      )}
    </div>
  );
}

interface ConnectorHealthCardProps {
  connector: ConnectorHealthData;
  onClick?: () => void;
}

function ConnectorHealthCard({ connector, onClick }: ConnectorHealthCardProps) {
  const healthColor = {
    healthy: 'border-green-500/30 bg-green-500/5',
    degraded: 'border-yellow-500/30 bg-yellow-500/5',
    unhealthy: 'border-red-500/30 bg-red-500/5',
  };

  const healthIndicator = {
    healthy: 'bg-green-500',
    degraded: 'bg-yellow-500',
    unhealthy: 'bg-red-500',
  };

  const statusText: Record<ConnectorStatus, string> = {
    connected: 'Connected',
    disconnected: 'Disconnected',
    syncing: 'Syncing',
    error: 'Error',
    configuring: 'Configuring',
  };

  const connectorIcon: Record<string, string> = {
    github: '?',
    s3: '?',
    sharepoint: '?',
    confluence: '?',
    notion: '?',
    slack: '?',
    postgresql: '?',
    mongodb: '?',
    fhir: '?',
    gdrive: '?',
  };

  const lastSyncFormatted = connector.lastSync
    ? formatTimeAgo(new Date(connector.lastSync))
    : 'Never';

  return (
    <button
      onClick={onClick}
      className={`p-4 rounded-lg border ${healthColor[connector.health]}
                 hover:opacity-80 transition-all text-left w-full`}
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-lg">{connectorIcon[connector.connectorType] || '?'}</span>
          <div>
            <div className="font-medium text-sm">{connector.connectorName}</div>
            <div className="text-xs text-text-muted">{statusText[connector.status]}</div>
          </div>
        </div>
        <div className={`w-3 h-3 rounded-full ${healthIndicator[connector.health]}`} />
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <div className="text-text-muted">Uptime</div>
          <div className="font-theme-data">{connector.uptime}%</div>
        </div>
        <div>
          <div className="text-text-muted">Error Rate</div>
          <div className="font-theme-data">{connector.errorRate}%</div>
        </div>
        <div>
          <div className="text-text-muted">Last Sync</div>
          <div className="font-theme-data">{lastSyncFormatted}</div>
        </div>
        <div>
          <div className="text-text-muted">Items</div>
          <div className="font-theme-data">{connector.itemsSynced.toLocaleString()}</div>
        </div>
      </div>
    </button>
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

/**
 * Convert ConnectorInfo to ConnectorHealthData for compatibility.
 */
export function connectorToHealthData(connector: ConnectorInfo): ConnectorHealthData {
  let health: 'healthy' | 'degraded' | 'unhealthy' = 'healthy';
  if (connector.status === 'error') {
    health = 'unhealthy';
  } else if (connector.status === 'disconnected') {
    health = 'degraded';
  }

  return {
    connectorId: connector.id,
    connectorName: connector.name,
    connectorType: connector.type,
    status: connector.status,
    uptime: connector.status === 'error' ? 85 : connector.status === 'disconnected' ? 0 : 99,
    lastSync: connector.last_sync || null,
    errorRate: connector.status === 'error' ? 25 : 2,
    avgSyncDuration: 180,
    itemsSynced: connector.items_synced || 0,
    health,
  };
}

export default ConnectorHealthGrid;
