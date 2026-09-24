'use client';

import { useState, useCallback, useEffect, useMemo } from 'react';
import { PanelTemplate } from '@/components/shared/PanelTemplate';
import { useApi } from '@/hooks/useApi';
import { useBackend } from '@/components/BackendSelector';
import {
  ConnectorCard,
  type ConnectorInfo,
  type ConnectorType,
  type ConnectorStatus,
} from './ConnectorCard';
import { ConnectorConfigModal } from './ConnectorConfigModal';
import { SyncStatusWidget, type SyncHistoryItem } from './SyncStatusWidget';
import { ConnectorHealthGrid, connectorToHealthData } from './ConnectorHealthGrid';
import { SyncTimeline } from './SyncTimeline';
import { logger } from '@/utils/logger';

export type ConnectorFilter = 'all' | 'connected' | 'disconnected' | 'error';
export type DashboardTab = 'connectors' | 'health' | 'sync-status' | 'scheduled';

export interface ConnectorDashboardProps {
  /** Callback when a connector is selected */
  onSelectConnector?: (connector: ConnectorInfo) => void;
  /** Enable real-time updates */
  enableRealtime?: boolean;
  /** Custom CSS classes */
  className?: string;
}

// Available connector types with metadata
const AVAILABLE_CONNECTORS: Omit<ConnectorInfo, 'id' | 'status' | 'last_sync' | 'items_synced'>[] =
  [
    {
      type: 'github',
      name: 'GitHub Enterprise',
      description: 'Sync repositories, issues, and pull requests from GitHub',
    },
    { type: 's3', name: 'Amazon S3', description: 'Index documents from S3 buckets' },
    {
      type: 'sharepoint',
      name: 'Microsoft SharePoint',
      description: 'Sync document libraries from SharePoint Online',
    },
    {
      type: 'confluence',
      name: 'Atlassian Confluence',
      description: 'Index spaces and pages from Confluence',
    },
    { type: 'notion', name: 'Notion', description: 'Sync workspaces and databases from Notion' },
    { type: 'slack', name: 'Slack', description: 'Index channel messages and threads' },
    { type: 'postgresql', name: 'PostgreSQL', description: 'Sync data from PostgreSQL databases' },
    { type: 'mongodb', name: 'MongoDB', description: 'Index collections from MongoDB' },
    {
      type: 'fhir',
      name: 'FHIR (Healthcare)',
      description: 'Connect to FHIR-compliant healthcare systems',
    },
    {
      type: 'gdrive',
      name: 'Google Drive',
      description: 'Sync documents and files from Google Drive',
    },
  ];

/**
 * Enterprise Connector Dashboard for managing data source connections.
 */
export function ConnectorDashboard({
  onSelectConnector,
  enableRealtime = true,
  className = '',
}: ConnectorDashboardProps) {
  const { config: backendConfig } = useBackend();
  const api = useApi(backendConfig?.api);

  // State
  const [connectors, setConnectors] = useState<ConnectorInfo[]>([]);
  const [syncHistory, setSyncHistory] = useState<SyncHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<DashboardTab>('connectors');
  const [filter, setFilter] = useState<ConnectorFilter>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedConnector, setSelectedConnector] = useState<ConnectorInfo | null>(null);
  const [configModalOpen, setConfigModalOpen] = useState(false);

  // Merge available connectors with configured connectors
  const mergedConnectors = useMemo(() => {
    const configured = new Map(connectors.map((c) => [c.type, c]));

    return AVAILABLE_CONNECTORS.map((available) => {
      const existing = configured.get(available.type as ConnectorType);
      if (existing) {
        return existing;
      }
      return {
        ...available,
        id: `${available.type}-new`,
        status: 'disconnected' as ConnectorStatus,
      };
    });
  }, [connectors]);

  // Filter connectors
  const filteredConnectors = useMemo(() => {
    let result = mergedConnectors;

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
      case 'connected':
        result = result.filter((c) => c.status === 'connected' || c.status === 'syncing');
        break;
      case 'disconnected':
        result = result.filter((c) => c.status === 'disconnected');
        break;
      case 'error':
        result = result.filter((c) => c.status === 'error');
        break;
    }

    return result;
  }, [mergedConnectors, filter, searchQuery]);

  // Load connectors
  const loadConnectors = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [connectorsResponse, historyResponse] = await Promise.all([
        api.get('/api/connectors').catch(() => ({ connectors: [] })) as Promise<{
          connectors: ConnectorInfo[];
        }>,
        api.get('/api/connectors/sync-history').catch(() => ({ history: [] })) as Promise<{
          history: SyncHistoryItem[];
        }>,
      ]);

      setConnectors(connectorsResponse.connectors || []);
      setSyncHistory(historyResponse.history || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load connectors');

      // Use mock data for demo
      setConnectors([
        {
          id: 'github-1',
          type: 'github',
          name: 'GitHub Enterprise',
          description: 'Sync repositories from GitHub',
          status: 'connected',
          last_sync: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
          items_synced: 15420,
        },
        {
          id: 'confluence-1',
          type: 'confluence',
          name: 'Atlassian Confluence',
          description: 'Index spaces and pages from Confluence',
          status: 'syncing',
          sync_progress: 0.67,
          items_synced: 3200,
        },
        {
          id: 'slack-1',
          type: 'slack',
          name: 'Slack',
          description: 'Index channel messages',
          status: 'error',
          error_message: 'Token expired. Please reconnect.',
          last_sync: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
          items_synced: 45000,
        },
      ]);

      setSyncHistory([
        {
          id: 'sync-1',
          connector_id: 'confluence-1',
          connector_name: 'Confluence',
          started_at: new Date().toISOString(),
          status: 'running',
          items_processed: 2140,
          items_total: 3200,
        },
        {
          id: 'sync-2',
          connector_id: 'github-1',
          connector_name: 'GitHub',
          started_at: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
          completed_at: new Date(Date.now() - 25 * 60 * 1000).toISOString(),
          status: 'completed',
          items_processed: 342,
          duration_seconds: 298,
        },
        {
          id: 'sync-3',
          connector_id: 'slack-1',
          connector_name: 'Slack',
          started_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
          completed_at: new Date(Date.now() - 2 * 60 * 60 * 1000 + 120000).toISOString(),
          status: 'failed',
          items_processed: 0,
          error_message: 'Authentication failed',
          duration_seconds: 2,
        },
      ]);
    } finally {
      setLoading(false);
    }
  }, [api]);

  // Load on mount
  useEffect(() => {
    loadConnectors();
  }, [loadConnectors]);

  // Polling for real-time updates
  useEffect(() => {
    if (!enableRealtime) return;

    const interval = setInterval(() => {
      loadConnectors();
    }, 10000);

    return () => clearInterval(interval);
  }, [enableRealtime, loadConnectors]);

  // Handle connector selection
  const handleSelectConnector = useCallback(
    (connector: ConnectorInfo) => {
      setSelectedConnector(connector);
      onSelectConnector?.(connector);
    },
    [onSelectConnector],
  );

  // Handle configure
  const handleConfigure = useCallback((connector: ConnectorInfo) => {
    setSelectedConnector(connector);
    setConfigModalOpen(true);
  }, []);

  // Handle sync
  const handleSync = useCallback(
    async (connector: ConnectorInfo) => {
      try {
        await api.post(`/api/connectors/${connector.id}/sync`);
        loadConnectors();
      } catch (err) {
        logger.error('Failed to start sync:', err);
      }
    },
    [api, loadConnectors],
  );

  // Handle disconnect
  const handleDisconnect = useCallback(
    async (connector: ConnectorInfo) => {
      if (
        !confirm(
          `Disconnect ${connector.name}? This will stop syncing but won't delete indexed data.`,
        )
      ) {
        return;
      }

      try {
        await api.delete(`/api/connectors/${connector.id}`);
        loadConnectors();
      } catch (err) {
        logger.error('Failed to disconnect:', err);
      }
    },
    [api, loadConnectors],
  );

  // Handle save config
  const handleSaveConfig = useCallback(
    async (connectorId: string, config: Record<string, unknown>) => {
      await api.put(`/api/connectors/${connectorId}`, { config });
      loadConnectors();
    },
    [api, loadConnectors],
  );

  // Handle test connection
  const handleTestConnection = useCallback(
    async (connectorId: string, config: Record<string, unknown>) => {
      const result = (await api.post(`/api/connectors/test`, {
        connector_id: connectorId,
        config,
      })) as { success: boolean };
      return result.success;
    },
    [api],
  );

  // Handle cancel sync
  const handleCancelSync = useCallback(
    async (syncId: string) => {
      try {
        await api.post(`/api/connectors/sync/${syncId}/cancel`);
        loadConnectors();
      } catch (err) {
        logger.error('Failed to cancel sync:', err);
      }
    },
    [api, loadConnectors],
  );

  // Handle retry sync
  const handleRetrySync = useCallback(
    async (connectorId: string) => {
      try {
        await api.post(`/api/connectors/${connectorId}/sync`);
        loadConnectors();
      } catch (err) {
        logger.error('Failed to retry sync:', err);
      }
    },
    [api, loadConnectors],
  );

  // Filter counts
  const filterCounts = useMemo(
    () => ({
      all: mergedConnectors.length,
      connected: mergedConnectors.filter((c) => c.status === 'connected' || c.status === 'syncing')
        .length,
      disconnected: mergedConnectors.filter((c) => c.status === 'disconnected').length,
      error: mergedConnectors.filter((c) => c.status === 'error').length,
    }),
    [mergedConnectors],
  );

  const tabs = [
    { id: 'connectors' as DashboardTab, label: 'Connectors' },
    { id: 'health' as DashboardTab, label: 'Health' },
    { id: 'sync-status' as DashboardTab, label: 'Sync Status' },
    { id: 'scheduled' as DashboardTab, label: 'Scheduled Jobs' },
  ];

  return (
    <PanelTemplate
      title="Enterprise Connectors"
      icon="  "
      loading={loading}
      error={error}
      onRefresh={loadConnectors}
      className={className}
    >
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

      {/* Connectors Tab */}
      {activeTab === 'connectors' && (
        <>
          {/* Search and filters */}
          <div className="mb-4 space-y-3">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search connectors..."
              className="w-full px-3 py-2 text-sm bg-surface border border-border rounded focus:border-[var(--accent)] focus:outline-none"
            />

            <div className="flex flex-wrap gap-1">
              {(['all', 'connected', 'disconnected', 'error'] as ConnectorFilter[]).map((f) => (
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

          {/* Connector grid */}
          <div className="grid gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
            {filteredConnectors.map((connector) => (
              <ConnectorCard
                key={connector.id}
                connector={connector}
                selected={selectedConnector?.id === connector.id}
                onSelect={handleSelectConnector}
                onConfigure={handleConfigure}
                onSync={handleSync}
                onDisconnect={handleDisconnect}
              />
            ))}
          </div>

          {filteredConnectors.length === 0 && (
            <div className="text-center py-8">
              <div className="text-4xl mb-2"> </div>
              <p className="text-text-muted">No connectors found</p>
            </div>
          )}
        </>
      )}

      {/* Health Tab */}
      {activeTab === 'health' && (
        <div className="space-y-6">
          <ConnectorHealthGrid
            connectors={mergedConnectors
              .filter((c) => c.status !== 'disconnected' || c.items_synced)
              .map(connectorToHealthData)}
            loading={loading}
            onConnectorClick={(connectorId) => {
              const connector = mergedConnectors.find((c) => c.id === connectorId);
              if (connector) {
                handleSelectConnector(connector);
                setActiveTab('connectors');
              }
            }}
          />
          <SyncTimeline
            history={syncHistory}
            loading={loading}
            hoursToShow={24}
            onSyncClick={(syncId) => {
              const sync = syncHistory.find((s) => s.id === syncId);
              if (sync) {
                const connector = mergedConnectors.find((c) => c.id === sync.connector_id);
                if (connector) {
                  handleSelectConnector(connector);
                }
              }
            }}
          />
        </div>
      )}

      {/* Sync Status Tab */}
      {activeTab === 'sync-status' && (
        <SyncStatusWidget
          connectors={mergedConnectors}
          syncHistory={syncHistory}
          onCancelSync={handleCancelSync}
          onRetrySync={handleRetrySync}
        />
      )}

      {/* Scheduled Jobs Tab */}
      {activeTab === 'scheduled' && (
        <div className="card p-6 text-center">
          <div className="text-4xl mb-2"> </div>
          <h3 className="font-theme-data text-lg mb-2">Scheduled Sync Jobs</h3>
          <p className="text-text-muted text-sm mb-4">
            Configure automatic sync schedules for your connectors.
          </p>
          <button
            onClick={() => setActiveTab('connectors')}
            className="px-4 py-2 text-sm font-theme-data bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 transition-colors"
          >
            Configure Connectors First
          </button>
        </div>
      )}

      {/* Config Modal */}
      <ConnectorConfigModal
        connector={selectedConnector}
        isOpen={configModalOpen}
        onClose={() => setConfigModalOpen(false)}
        onSave={handleSaveConfig}
        onTest={handleTestConnection}
      />
    </PanelTemplate>
  );
}

export default ConnectorDashboard;
