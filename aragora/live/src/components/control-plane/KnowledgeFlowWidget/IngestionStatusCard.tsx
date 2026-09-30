'use client';

import { useMemo } from 'react';

export type IngestionStatus = 'idle' | 'ingesting' | 'processing' | 'complete' | 'error';

export interface ConnectorIngestionStatus {
  connector_id: string;
  connector_name: string;
  connector_type: string;
  status: IngestionStatus;
  docs_indexed: number;
  docs_total: number;
  docs_failed: number;
  last_ingestion?: string;
  error_message?: string;
  progress?: number;
}

export interface IngestionStatusCardProps {
  connectors: ConnectorIngestionStatus[];
  loading?: boolean;
  onRetry?: (connectorId: string) => void;
  onViewDetails?: (connector: ConnectorIngestionStatus) => void;
  className?: string;
}

const CONNECTOR_ICONS: Record<string, string> = {
  github: '🐙',
  s3: '📦',
  sharepoint: '📁',
  confluence: '📝',
  notion: '📓',
  slack: '💬',
  gdrive: '📂',
  postgresql: '🐘',
  mongodb: '🍃',
  fhir: '🏥',
};

function _getStatusColor(status: IngestionStatus): string {
  switch (status) {
    case 'complete':
      return 'text-[var(--accent)]';
    case 'ingesting':
    case 'processing':
      return 'text-cyan-400';
    case 'error':
      return 'text-red-400';
    default:
      return 'text-text-muted';
  }
}

function getStatusBadgeClass(status: IngestionStatus): string {
  switch (status) {
    case 'complete':
      return 'bg-[var(--accent)]/20 text-[var(--accent)]';
    case 'ingesting':
    case 'processing':
      return 'bg-cyan-400/20 text-cyan-400';
    case 'error':
      return 'bg-red-400/20 text-red-400';
    default:
      return 'bg-surface text-text-muted';
  }
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

function formatNumber(n: number): string {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return n.toString();
}

/**
 * Card showing ingestion status for all connected data sources.
 */
export function IngestionStatusCard({
  connectors,
  loading = false,
  onRetry,
  onViewDetails,
  className = '',
}: IngestionStatusCardProps) {
  const summary = useMemo(() => {
    const totalDocs = connectors.reduce((sum, c) => sum + c.docs_indexed, 0);
    const totalFailed = connectors.reduce((sum, c) => sum + c.docs_failed, 0);
    const activeConnectors = connectors.filter(
      (c) => c.status === 'ingesting' || c.status === 'processing',
    ).length;
    const errorConnectors = connectors.filter((c) => c.status === 'error').length;

    return {
      totalDocs,
      totalFailed,
      activeConnectors,
      errorConnectors,
      healthyConnectors: connectors.length - errorConnectors,
    };
  }, [connectors]);

  if (loading) {
    return (
      <div className={`card p-4 ${className}`}>
        <div className="animate-pulse space-y-3">
          <div className="h-4 bg-surface rounded w-1/3" />
          <div className="h-20 bg-surface rounded" />
        </div>
      </div>
    );
  }

  return (
    <div className={`card p-4 ${className}`}>
      <h3 className="font-theme-data font-bold text-sm mb-3 flex items-center gap-2">
        <span>📥</span> Ingestion Status
      </h3>

      {/* Summary Stats */}
      <div className="grid grid-cols-4 gap-2 mb-4">
        <div className="bg-surface rounded p-2 text-center">
          <div className="text-lg font-theme-data font-bold text-[var(--accent)]">
            {formatNumber(summary.totalDocs)}
          </div>
          <div className="text-xs text-text-muted">Indexed</div>
        </div>
        <div className="bg-surface rounded p-2 text-center">
          <div className="text-lg font-theme-data font-bold text-cyan-400">
            {summary.activeConnectors}
          </div>
          <div className="text-xs text-text-muted">Active</div>
        </div>
        <div className="bg-surface rounded p-2 text-center">
          <div className="text-lg font-theme-data font-bold text-red-400">
            {formatNumber(summary.totalFailed)}
          </div>
          <div className="text-xs text-text-muted">Failed</div>
        </div>
        <div className="bg-surface rounded p-2 text-center">
          <div
            className={`text-lg font-theme-data font-bold ${
              summary.errorConnectors > 0 ? 'text-red-400' : 'text-[var(--accent)]'
            }`}
          >
            {summary.healthyConnectors}/{connectors.length}
          </div>
          <div className="text-xs text-text-muted">Healthy</div>
        </div>
      </div>

      {/* Connector List */}
      <div className="space-y-2">
        {connectors.length === 0 ? (
          <div className="text-center py-4 text-text-muted text-sm">No connectors configured</div>
        ) : (
          connectors.map((connector) => (
            <div
              key={connector.connector_id}
              onClick={() => onViewDetails?.(connector)}
              className="bg-surface rounded p-3 cursor-pointer hover:bg-surface-alt transition-colors"
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-lg">
                    {CONNECTOR_ICONS[connector.connector_type] || '📄'}
                  </span>
                  <span className="font-theme-data text-sm">{connector.connector_name}</span>
                </div>
                <span
                  className={`px-2 py-0.5 rounded text-xs font-theme-data ${getStatusBadgeClass(
                    connector.status,
                  )}`}
                >
                  {connector.status.toUpperCase()}
                </span>
              </div>

              {/* Progress bar for active ingestion */}
              {(connector.status === 'ingesting' || connector.status === 'processing') && (
                <div className="mb-2">
                  <div className="h-1.5 bg-surface-alt rounded overflow-hidden">
                    <div
                      className="h-full bg-cyan-400 transition-all duration-500"
                      style={{
                        width: `${
                          connector.progress ??
                          (connector.docs_total > 0
                            ? (connector.docs_indexed / connector.docs_total) * 100
                            : 0)
                        }%`,
                      }}
                    />
                  </div>
                  <div className="text-xs text-text-muted mt-1">
                    {formatNumber(connector.docs_indexed)} / {formatNumber(connector.docs_total)}{' '}
                    docs
                  </div>
                </div>
              )}

              {/* Stats row */}
              <div className="flex items-center justify-between text-xs text-text-muted">
                <span>
                  {formatNumber(connector.docs_indexed)} docs indexed
                  {connector.docs_failed > 0 && (
                    <span className="text-red-400 ml-1">({connector.docs_failed} failed)</span>
                  )}
                </span>
                {connector.last_ingestion && <span>{formatTime(connector.last_ingestion)}</span>}
              </div>

              {/* Error message */}
              {connector.status === 'error' && connector.error_message && (
                <div className="mt-2 flex items-center justify-between">
                  <span className="text-xs text-red-400 truncate flex-1">
                    ⚠ {connector.error_message}
                  </span>
                  {onRetry && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onRetry(connector.connector_id);
                      }}
                      className="ml-2 px-2 py-1 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] rounded hover:bg-[var(--accent)]/30 transition-colors"
                    >
                      Retry
                    </button>
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default IngestionStatusCard;
