'use client';

import { useState, useCallback, useEffect, useMemo } from 'react';
import { PanelTemplate } from '@/components/shared/PanelTemplate';
import { useApi } from '@/hooks/useApi';
import { useBackend } from '@/components/BackendSelector';
import { IngestionStatusCard, type ConnectorIngestionStatus } from './IngestionStatusCard';
import { KnowledgeAgeHistogram, type AgeDistribution } from './KnowledgeAgeHistogram';
import { logger } from '@/utils/logger';

export interface KnowledgeFlowStats {
  total_docs: number;
  total_chunks: number;
  total_embeddings: number;
  storage_used_mb: number;
  last_ingestion?: string;
  next_scheduled_refresh?: string;
}

export interface RefreshSchedule {
  connector_id: string;
  connector_name: string;
  schedule: string; // cron expression or human readable
  next_run?: string;
  enabled: boolean;
}

export interface KnowledgeFlowWidgetProps {
  /** Enable real-time updates */
  enableRealtime?: boolean;
  /** Auto-refresh interval in ms */
  refreshInterval?: number;
  /** Custom CSS classes */
  className?: string;
}

/**
 * Knowledge Flow Widget showing ingestion status, age distribution, and refresh schedules.
 * Provides visibility into knowledge freshness and connector health.
 */
export function KnowledgeFlowWidget({
  enableRealtime = true,
  refreshInterval = 30000,
  className = '',
}: KnowledgeFlowWidgetProps) {
  const { config: backendConfig } = useBackend();
  const api = useApi(backendConfig?.api);

  // State
  const [connectors, setConnectors] = useState<ConnectorIngestionStatus[]>([]);
  const [stats, setStats] = useState<KnowledgeFlowStats | null>(null);
  const [ageDistribution, setAgeDistribution] = useState<AgeDistribution[]>([]);
  const [refreshSchedules, setRefreshSchedules] = useState<RefreshSchedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [autoRefresh, setAutoRefresh] = useState(enableRealtime);

  // Load all data
  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [connectorsRes, statsRes, ageRes, schedulesRes] = await Promise.all([
        api.get('/api/knowledge/ingestion-status').catch(() => ({ connectors: [] })) as Promise<{
          connectors: ConnectorIngestionStatus[];
        }>,
        api.get('/api/knowledge/stats').catch(() => ({})) as Promise<KnowledgeFlowStats>,
        api.get('/api/knowledge/age-distribution').catch(() => ({ distribution: [] })) as Promise<{
          distribution: AgeDistribution[];
        }>,
        api.get('/api/knowledge/refresh-schedules').catch(() => ({ schedules: [] })) as Promise<{
          schedules: RefreshSchedule[];
        }>,
      ]);

      setConnectors(connectorsRes.connectors || []);
      setStats(statsRes);
      setAgeDistribution(ageRes.distribution || []);
      setRefreshSchedules(schedulesRes.schedules || []);
      setLastRefresh(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load knowledge flow data');

      // Use mock data for demo
      setConnectors([
        {
          connector_id: 'github-1',
          connector_name: 'GitHub Enterprise',
          connector_type: 'github',
          status: 'complete',
          docs_indexed: 15420,
          docs_total: 15420,
          docs_failed: 12,
          last_ingestion: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
        },
        {
          connector_id: 'confluence-1',
          connector_name: 'Confluence',
          connector_type: 'confluence',
          status: 'ingesting',
          docs_indexed: 2140,
          docs_total: 3200,
          docs_failed: 0,
          progress: 67,
        },
        {
          connector_id: 'slack-1',
          connector_name: 'Slack',
          connector_type: 'slack',
          status: 'error',
          docs_indexed: 45000,
          docs_total: 45000,
          docs_failed: 0,
          error_message: 'Token expired',
          last_ingestion: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
        },
        {
          connector_id: 'notion-1',
          connector_name: 'Notion',
          connector_type: 'notion',
          status: 'complete',
          docs_indexed: 8500,
          docs_total: 8500,
          docs_failed: 3,
          last_ingestion: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
        },
      ]);

      setStats({
        total_docs: 71060,
        total_chunks: 425000,
        total_embeddings: 425000,
        storage_used_mb: 2340,
        last_ingestion: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
        next_scheduled_refresh: new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString(),
      });

      setAgeDistribution([
        { bucket: '< 1 day', count: 12500, percentage: 17.6 },
        { bucket: '1-7 days', count: 28000, percentage: 39.4 },
        { bucket: '1-4 weeks', count: 21000, percentage: 29.6 },
        { bucket: '> 1 month', count: 9560, percentage: 13.4 },
      ]);

      setRefreshSchedules([
        {
          connector_id: 'github-1',
          connector_name: 'GitHub',
          schedule: 'Every 6 hours',
          next_run: new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString(),
          enabled: true,
        },
        {
          connector_id: 'confluence-1',
          connector_name: 'Confluence',
          schedule: 'Daily at 2 AM',
          next_run: new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString(),
          enabled: true,
        },
        {
          connector_id: 'slack-1',
          connector_name: 'Slack',
          schedule: 'Every 4 hours',
          enabled: false,
        },
      ]);

      setLastRefresh(new Date());
    } finally {
      setLoading(false);
    }
  }, [api]);

  // Load on mount
  useEffect(() => {
    loadData();
  }, [loadData]);

  // Auto-refresh
  useEffect(() => {
    if (!autoRefresh) return;

    const interval = setInterval(() => {
      loadData();
    }, refreshInterval);

    return () => clearInterval(interval);
  }, [autoRefresh, refreshInterval, loadData]);

  // Handle retry ingestion
  const handleRetry = useCallback(
    async (connectorId: string) => {
      try {
        await api.post(`/api/connectors/${connectorId}/sync`);
        loadData();
      } catch (err) {
        logger.error('Failed to retry ingestion:', err);
      }
    },
    [api, loadData],
  );

  // Handle force refresh
  const handleForceRefresh = useCallback(async () => {
    try {
      await api.post('/api/knowledge/refresh-all');
      loadData();
    } catch (err) {
      logger.error('Failed to force refresh:', err);
    }
  }, [api, loadData]);

  // Format time until next refresh
  const timeUntilNextRefresh = useMemo(() => {
    if (!stats?.next_scheduled_refresh) return null;
    const next = new Date(stats.next_scheduled_refresh);
    const now = new Date();
    const diffMs = next.getTime() - now.getTime();
    if (diffMs <= 0) return 'Now';
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 60) return `${diffMins}m`;
    return `${Math.floor(diffMins / 60)}h ${diffMins % 60}m`;
  }, [stats?.next_scheduled_refresh]);

  return (
    <PanelTemplate
      title="Knowledge Flow"
      icon="🧠"
      loading={loading}
      error={error}
      onRefresh={loadData}
      className={className}
    >
      {/* Global Stats */}
      {stats && (
        <div className="grid grid-cols-4 gap-3 mb-4">
          <div className="bg-surface rounded p-3 text-center">
            <div className="text-xl font-theme-data font-bold text-[var(--accent)]">
              {(stats.total_docs / 1000).toFixed(1)}K
            </div>
            <div className="text-xs text-text-muted">Documents</div>
          </div>
          <div className="bg-surface rounded p-3 text-center">
            <div className="text-xl font-theme-data font-bold text-cyan-400">
              {(stats.total_chunks / 1000).toFixed(0)}K
            </div>
            <div className="text-xs text-text-muted">Chunks</div>
          </div>
          <div className="bg-surface rounded p-3 text-center">
            <div className="text-xl font-theme-data font-bold text-purple-400">
              {(stats.storage_used_mb / 1000).toFixed(1)}GB
            </div>
            <div className="text-xs text-text-muted">Storage</div>
          </div>
          <div className="bg-surface rounded p-3 text-center">
            <div className="text-xl font-theme-data font-bold text-yellow-400">
              {timeUntilNextRefresh || '--'}
            </div>
            <div className="text-xs text-text-muted">Next Refresh</div>
          </div>
        </div>
      )}

      {/* Auto-refresh indicator */}
      <div className="flex items-center justify-between mb-4 p-2 bg-surface rounded">
        <div className="flex items-center gap-2">
          <span
            className={`w-2 h-2 rounded-full ${
              autoRefresh ? 'bg-[var(--accent)] animate-pulse' : 'bg-text-muted'
            }`}
          />
          <span className="text-xs text-text-muted">
            Auto-refresh {autoRefresh ? 'enabled' : 'disabled'}
          </span>
          <span className="text-xs text-text-muted">Last: {lastRefresh.toLocaleTimeString()}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={`px-2 py-1 text-xs font-theme-data rounded transition-colors ${
              autoRefresh
                ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                : 'bg-surface-alt text-text-muted'
            }`}
          >
            {autoRefresh ? 'Pause' : 'Resume'}
          </button>
          <button
            onClick={handleForceRefresh}
            className="px-2 py-1 text-xs font-theme-data bg-surface-alt hover:bg-surface text-text-muted hover:text-text rounded transition-colors"
          >
            Force Refresh
          </button>
        </div>
      </div>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Left: Ingestion Status */}
        <IngestionStatusCard connectors={connectors} loading={loading} onRetry={handleRetry} />

        {/* Right: Age Distribution */}
        <KnowledgeAgeHistogram
          distribution={ageDistribution}
          totalDocs={stats?.total_docs || 0}
          staleThresholdDays={30}
          loading={loading}
        />
      </div>

      {/* Refresh Schedules */}
      <div className="card p-4 mt-4">
        <h3 className="font-theme-data font-bold text-sm mb-3 flex items-center gap-2">
          <span>⏰</span> Refresh Schedules
        </h3>
        <div className="space-y-2">
          {refreshSchedules.length === 0 ? (
            <div className="text-center py-4 text-text-muted text-sm">
              No refresh schedules configured
            </div>
          ) : (
            refreshSchedules.map((schedule) => (
              <div
                key={schedule.connector_id}
                className="flex items-center justify-between p-2 bg-surface rounded"
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      schedule.enabled ? 'bg-[var(--accent)]' : 'bg-text-muted'
                    }`}
                  />
                  <span className="font-theme-data text-sm">{schedule.connector_name}</span>
                </div>
                <div className="flex items-center gap-4 text-xs text-text-muted">
                  <span>{schedule.schedule}</span>
                  {schedule.next_run && schedule.enabled && (
                    <span className="text-cyan-400">
                      Next: {new Date(schedule.next_run).toLocaleTimeString()}
                    </span>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </PanelTemplate>
  );
}

export default KnowledgeFlowWidget;
