'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useToastContext } from '@/context/ToastContext';
import { API_BASE_URL } from '@/config';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { logger } from '@/utils/logger';
import { useConnectorWebSocket, type ConnectorSyncState } from '@/hooks/useConnectorWebSocket';
import {
  type Connector,
  type ConnectorDetails,
  type SchedulerStats,
  type SyncHistoryEntry,
  CONNECTOR_TYPE_ICONS,
  CONNECTOR_TYPE_COLORS,
  CONNECTOR_CATEGORIES,
  formatRelativeTime,
} from './types';

function ConnectorCard({
  connector,
  onSync,
  onCancelSync,
  onEdit,
  onDelete,
  onViewDetails,
  syncing,
}: {
  connector: Connector;
  onSync: () => void;
  onCancelSync: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onViewDetails: () => void;
  syncing: boolean;
}) {
  const schedule = connector.schedule ?? { interval_minutes: 60, enabled: false };
  const connectorType = connector.type || connector.id.split(':')[0] || 'unknown';
  const connectorId = connector.name || connector.id.split(':').pop() || connector.id;
  const isRunning = connector.is_running || connector.status === 'syncing';

  return (
    <div
      className={`
        p-5 rounded-lg border-2 transition-all cursor-pointer hover:shadow-lg
        ${CONNECTOR_TYPE_COLORS[connectorType] || 'border-gray-500 bg-gray-500/10'}
      `}
      onClick={onViewDetails}
    >
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <span className="text-3xl">{CONNECTOR_TYPE_ICONS[connectorType] || '🔗'}</span>
          <div>
            <h3 className="font-theme-data font-bold text-text">{connectorId}</h3>
            <span className="text-xs text-text-muted font-theme-data uppercase">
              {connectorType}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {isRunning && (
            <span className="px-2 py-1 text-xs bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/50 rounded font-theme-data animate-pulse">
              SYNCING{' '}
              {connector.sync_progress ? `${Math.round(connector.sync_progress * 100)}%` : ''}
            </span>
          )}
          {connector.status === 'error' && (
            <span className="px-2 py-1 text-xs bg-red-500/20 text-red-400 border border-red-500/50 rounded font-theme-data">
              ERROR
            </span>
          )}
          {connector.consecutive_failures > 0 && !connector.status?.includes('error') && (
            <span className="px-2 py-1 text-xs bg-red-500/20 text-red-400 border border-red-500/50 rounded font-theme-data">
              {connector.consecutive_failures} FAILURES
            </span>
          )}
        </div>
      </div>

      {/* Sync Progress Bar */}
      {isRunning && connector.sync_progress !== undefined && (
        <div className="mb-4">
          <div className="h-2 bg-bg rounded-full overflow-hidden">
            <div
              className="h-full bg-[var(--accent)] transition-all duration-300"
              style={{ width: `${connector.sync_progress * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* Stats & Schedule Info */}
      <div className="mb-4 p-3 bg-bg/50 rounded">
        <div className="grid grid-cols-2 gap-2 text-xs font-theme-data">
          <div>
            <span className="text-text-muted">Schedule:</span>
            <span className="ml-2 text-text">
              {schedule.cron_expression || `Every ${schedule.interval_minutes || 60}m`}
            </span>
          </div>
          <div>
            <span className="text-text-muted">Status:</span>
            <span
              className={`ml-2 ${schedule.enabled ? 'text-[var(--accent)]' : 'text-text-muted'}`}
            >
              {schedule.enabled ? 'ENABLED' : 'DISABLED'}
            </span>
          </div>
          {connector.last_run && (
            <div>
              <span className="text-text-muted">Last Run:</span>
              <span className="ml-2 text-text">{formatRelativeTime(connector.last_run)}</span>
            </div>
          )}
          {connector.items_synced !== undefined && (
            <div>
              <span className="text-text-muted">Items:</span>
              <span className="ml-2 text-text">{connector.items_synced.toLocaleString()}</span>
            </div>
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
        {isRunning ? (
          <button
            onClick={onCancelSync}
            className="flex-1 px-3 py-2 bg-red-500/20 border border-red-500/50 text-red-400 font-theme-data text-sm hover:bg-red-500/30 transition-colors rounded"
          >
            CANCEL SYNC
          </button>
        ) : (
          <button
            onClick={onSync}
            disabled={syncing}
            className="flex-1 px-3 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/50 text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors rounded"
          >
            {syncing ? 'SYNCING...' : 'SYNC NOW'}
          </button>
        )}
        <button
          onClick={onEdit}
          className="px-3 py-2 bg-blue-500/20 border border-blue-500/50 text-blue-400 font-theme-data text-sm hover:bg-blue-500/30 transition-colors rounded"
        >
          EDIT
        </button>
        <button
          onClick={onDelete}
          className="px-3 py-2 bg-red-500/20 border border-red-500/50 text-red-400 font-theme-data text-sm hover:bg-red-500/30 transition-colors rounded"
        >
          DELETE
        </button>
      </div>
    </div>
  );
}

function EditConnectorModal({
  connector,
  onClose,
  onSave,
}: {
  connector: Connector;
  onClose: () => void;
  onSave: (updates: { schedule: Connector['schedule'] }) => void;
}) {
  const schedule = connector.schedule ?? { interval_minutes: 60, enabled: false };
  const [intervalMinutes, setIntervalMinutes] = useState(schedule.interval_minutes || 60);
  const [cronExpression, setCronExpression] = useState(schedule.cron_expression || '');
  const [enabled, setEnabled] = useState(schedule.enabled);
  const [useCron, setUseCron] = useState(!!schedule.cron_expression);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave({
      schedule: {
        interval_minutes: useCron ? undefined : intervalMinutes,
        cron_expression: useCron ? cronExpression : undefined,
        enabled,
      },
    });
  };

  const connectorType = connector.type || connector.id.split(':')[0] || 'unknown';
  const connectorId = connector.id.split(':').pop() || connector.id;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 backdrop-blur-sm">
      <div className="w-full max-w-lg bg-surface border border-border rounded-lg shadow-2xl">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <div className="flex items-center gap-3">
            <span className="text-2xl">{CONNECTOR_TYPE_ICONS[connectorType] || '🔗'}</span>
            <div>
              <h2 className="text-lg font-theme-data font-bold text-text">Edit Connector</h2>
              <span className="text-xs text-text-muted font-theme-data">{connectorId}</span>
            </div>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text">
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4">
          {/* Schedule Type Toggle */}
          <div className="mb-4">
            <label className="block text-xs font-theme-data text-text-muted uppercase mb-2">
              Schedule Type
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setUseCron(false)}
                className={`flex-1 px-3 py-2 rounded border-2 transition-all text-sm font-theme-data ${
                  !useCron
                    ? 'border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
                    : 'border-border text-text-muted hover:border-text'
                }`}
              >
                Interval
              </button>
              <button
                type="button"
                onClick={() => setUseCron(true)}
                className={`flex-1 px-3 py-2 rounded border-2 transition-all text-sm font-theme-data ${
                  useCron
                    ? 'border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
                    : 'border-border text-text-muted hover:border-text'
                }`}
              >
                Cron Expression
              </button>
            </div>
          </div>

          {/* Interval or Cron Input */}
          {useCron ? (
            <div className="mb-4">
              <label className="block text-xs font-theme-data text-text-muted uppercase mb-1">
                Cron Expression
              </label>
              <input
                type="text"
                value={cronExpression}
                onChange={(e) => setCronExpression(e.target.value)}
                placeholder="0 * * * *"
                className="w-full px-3 py-2 bg-bg border border-border rounded text-sm font-theme-data text-text focus:border-[var(--accent)] focus:outline-none"
              />
              <p className="text-xs text-text-muted mt-1">Example: 0 */6 * * * (every 6 hours)</p>
            </div>
          ) : (
            <div className="mb-4">
              <label className="block text-xs font-theme-data text-text-muted uppercase mb-1">
                Interval (minutes)
              </label>
              <input
                type="number"
                value={intervalMinutes}
                onChange={(e) => setIntervalMinutes(parseInt(e.target.value) || 60)}
                min={1}
                max={1440}
                className="w-full px-3 py-2 bg-bg border border-border rounded text-sm font-theme-data text-text focus:border-[var(--accent)] focus:outline-none"
              />
              <p className="text-xs text-text-muted mt-1">Sync every {intervalMinutes} minutes</p>
            </div>
          )}

          {/* Enabled Toggle */}
          <div className="mb-6">
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                className="w-4 h-4 accent-acid-green"
              />
              <span className="text-sm font-theme-data text-text">Enable automatic sync</span>
            </label>
          </div>

          {/* Actions */}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 bg-surface border border-border text-text font-theme-data text-sm hover:border-text transition-colors rounded"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="flex-1 px-4 py-2 bg-[var(--accent)] text-bg font-theme-data text-sm font-bold hover:bg-[var(--accent)]/80 transition-colors rounded"
            >
              Save Changes
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function AddConnectorModal({
  onClose,
  onAdd,
}: {
  onClose: () => void;
  onAdd: (type: string, config: Record<string, string>) => void;
}) {
  const [type, setType] = useState('github');
  const [config, setConfig] = useState<Record<string, string>>({});

  const configFields: Record<string, { label: string; placeholder: string; required?: boolean }[]> =
    {
      github: [
        { label: 'owner', placeholder: 'Organization/User', required: true },
        { label: 'repo', placeholder: 'Repository name', required: true },
        { label: 'token', placeholder: 'GitHub token (optional)' },
      ],
      s3: [
        { label: 'bucket', placeholder: 'Bucket name', required: true },
        { label: 'prefix', placeholder: 'Path prefix (optional)' },
        { label: 'region', placeholder: 'AWS region' },
      ],
      postgres: [
        { label: 'host', placeholder: 'Database host', required: true },
        { label: 'database', placeholder: 'Database name', required: true },
        { label: 'schema', placeholder: 'Schema (default: public)' },
      ],
      mongodb: [
        { label: 'connection_string', placeholder: 'MongoDB URI', required: true },
        { label: 'database', placeholder: 'Database name', required: true },
      ],
      fhir: [
        { label: 'base_url', placeholder: 'FHIR server URL', required: true },
        { label: 'organization_id', placeholder: 'Organization ID', required: true },
        { label: 'client_id', placeholder: 'OAuth client ID' },
      ],
    };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onAdd(type, config);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 backdrop-blur-sm">
      <div className="w-full max-w-lg bg-surface border border-border rounded-lg shadow-2xl">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h2 className="text-lg font-theme-data font-bold text-text">Add Connector</h2>
          <button onClick={onClose} className="text-text-muted hover:text-text">
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4">
          {/* Connector Type */}
          <div className="mb-4">
            <label className="block text-xs font-theme-data text-text-muted uppercase mb-2">
              Connector Type
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2">
              {Object.entries(CONNECTOR_TYPE_ICONS).map(([t, icon]) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => {
                    setType(t);
                    setConfig({});
                  }}
                  className={`
                    p-3 rounded border-2 transition-all text-center
                    ${
                      type === t
                        ? 'border-[var(--accent)] bg-[var(--accent)]/20'
                        : 'border-border hover:border-text'
                    }
                  `}
                >
                  <span className="text-2xl">{icon}</span>
                  <span className="block text-xs font-theme-data mt-1 capitalize">{t}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Config Fields */}
          <div className="space-y-3 mb-6">
            {configFields[type]?.map((field) => (
              <div key={field.label}>
                <label className="block text-xs font-theme-data text-text-muted uppercase mb-1">
                  {field.label}
                  {field.required && <span className="text-red-400 ml-1">*</span>}
                </label>
                <input
                  type="text"
                  value={config[field.label] || ''}
                  onChange={(e) => setConfig({ ...config, [field.label]: e.target.value })}
                  placeholder={field.placeholder}
                  required={field.required}
                  className="w-full px-3 py-2 bg-bg border border-border rounded text-sm font-theme-data text-text focus:border-[var(--accent)] focus:outline-none"
                />
              </div>
            ))}
          </div>

          {/* Actions */}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 bg-surface border border-border text-text font-theme-data text-sm hover:border-text transition-colors rounded"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="flex-1 px-4 py-2 bg-[var(--accent)] text-bg font-theme-data text-sm font-bold hover:bg-[var(--accent)]/80 transition-colors rounded"
            >
              Add Connector
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ConnectorDetailsModal({
  connectorId,
  apiBase,
  onClose,
  onSync,
  onCancelSync,
}: {
  connectorId: string;
  apiBase: string;
  onClose: () => void;
  onSync: () => void;
  onCancelSync: (syncId: string) => void;
}) {
  const [details, setDetails] = useState<ConnectorDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'overview' | 'logs' | 'config'>('overview');

  useEffect(() => {
    const fetchDetails = async () => {
      try {
        setLoading(true);
        const response = await fetch(`${apiBase}/api/connectors/${connectorId}`);
        if (response.ok) {
          const data = await response.json();
          setDetails(data);
        }
      } catch (error) {
        logger.error('Failed to fetch connector details:', error);
      } finally {
        setLoading(false);
      }
    };
    fetchDetails();
  }, [connectorId, apiBase]);

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 backdrop-blur-sm">
        <div className="text-text-muted font-theme-data animate-pulse">Loading...</div>
      </div>
    );
  }

  if (!details) {
    return null;
  }

  const connectorType = details.type || details.id.split(':')[0] || 'unknown';
  const schedule = details.schedule ?? { interval_minutes: 60, enabled: false };
  const isRunning = details.is_running || details.status === 'syncing';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 backdrop-blur-sm">
      <div className="w-full max-w-3xl max-h-[90vh] mx-4 sm:mx-0 bg-surface border border-border rounded-lg shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-border">
          <div className="flex items-center gap-3">
            <span className="text-3xl">{CONNECTOR_TYPE_ICONS[connectorType] || '🔗'}</span>
            <div>
              <h2 className="text-lg font-theme-data font-bold text-text">
                {details.name || details.id.split(':').pop()}
              </h2>
              <div className="flex items-center gap-2">
                <span className="text-xs text-text-muted font-theme-data uppercase">
                  {connectorType}
                </span>
                {details.category && (
                  <span
                    className={`text-xs px-2 py-0.5 rounded font-theme-data ${CONNECTOR_CATEGORIES[details.category]?.color || 'bg-gray-500/20 text-gray-400'}`}
                  >
                    {details.category}
                  </span>
                )}
              </div>
            </div>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text text-2xl">
            ✕
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-border">
          {(['overview', 'logs', 'config'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`flex-1 px-4 py-3 font-theme-data text-sm uppercase transition-colors ${
                activeTab === tab
                  ? 'text-[var(--accent)] border-b-2 border-[var(--accent)] bg-[var(--accent)]/5'
                  : 'text-text-muted hover:text-text'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          {activeTab === 'overview' && (
            <div className="space-y-4">
              {/* Status Card */}
              <div className="p-4 bg-bg rounded-lg border border-border">
                <h3 className="text-sm font-theme-data font-bold text-text mb-3">STATUS</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div>
                    <div className="text-xs text-text-muted font-theme-data">Status</div>
                    <div
                      className={`font-theme-data font-bold ${
                        details.status === 'connected' || details.status === 'configured'
                          ? 'text-[var(--accent)]'
                          : details.status === 'error'
                            ? 'text-red-400'
                            : details.status === 'syncing'
                              ? 'text-yellow-400'
                              : 'text-text-muted'
                      }`}
                    >
                      {details.status?.toUpperCase() || 'UNKNOWN'}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-text-muted font-theme-data">Items Synced</div>
                    <div className="font-theme-data font-bold text-text">
                      {(details.items_synced || 0).toLocaleString()}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-text-muted font-theme-data">Last Run</div>
                    <div className="font-theme-data text-text">
                      {details.last_run ? formatRelativeTime(details.last_run) : 'Never'}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-text-muted font-theme-data">Failures</div>
                    <div
                      className={`font-theme-data font-bold ${
                        details.consecutive_failures > 0 ? 'text-red-400' : 'text-[var(--accent)]'
                      }`}
                    >
                      {details.consecutive_failures}
                    </div>
                  </div>
                </div>
                {details.error_message && (
                  <div className="mt-3 p-2 bg-red-500/10 border border-red-500/30 rounded text-sm text-red-400 font-theme-data">
                    {details.error_message}
                  </div>
                )}
              </div>

              {/* Schedule Card */}
              <div className="p-4 bg-bg rounded-lg border border-border">
                <h3 className="text-sm font-theme-data font-bold text-text mb-3">SCHEDULE</h3>
                <div className="grid grid-cols-2 gap-4 text-sm font-theme-data">
                  <div>
                    <span className="text-text-muted">Type:</span>
                    <span className="ml-2 text-text">
                      {schedule.cron_expression ? 'Cron' : 'Interval'}
                    </span>
                  </div>
                  <div>
                    <span className="text-text-muted">Value:</span>
                    <span className="ml-2 text-text">
                      {schedule.cron_expression || `${schedule.interval_minutes || 60}m`}
                    </span>
                  </div>
                  <div>
                    <span className="text-text-muted">Enabled:</span>
                    <span
                      className={`ml-2 ${schedule.enabled ? 'text-[var(--accent)]' : 'text-red-400'}`}
                    >
                      {schedule.enabled ? 'YES' : 'NO'}
                    </span>
                  </div>
                  <div>
                    <span className="text-text-muted">Next Run:</span>
                    <span className="ml-2 text-text">
                      {details.next_run
                        ? new Date(details.next_run).toLocaleString()
                        : 'Not scheduled'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Actions */}
              <div className="flex gap-2">
                {isRunning ? (
                  <button
                    onClick={() => details.current_run_id && onCancelSync(details.current_run_id)}
                    className="flex-1 px-4 py-2 bg-red-500/20 border border-red-500/50 text-red-400 font-theme-data hover:bg-red-500/30 transition-colors rounded"
                  >
                    Cancel Current Sync
                  </button>
                ) : (
                  <button
                    onClick={onSync}
                    className="flex-1 px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/50 text-[var(--accent)] font-theme-data hover:bg-[var(--accent)]/30 transition-colors rounded"
                  >
                    Sync Now
                  </button>
                )}
              </div>
            </div>
          )}

          {activeTab === 'logs' && (
            <div className="space-y-2">
              <h3 className="text-sm font-theme-data font-bold text-text mb-3">SYNC HISTORY</h3>
              {details.recent_syncs && details.recent_syncs.length > 0 ? (
                details.recent_syncs.map((sync, idx) => (
                  <div
                    key={sync.id || sync.run_id || idx}
                    className="p-3 bg-bg rounded-lg border border-border"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span
                        className={`text-xs font-theme-data px-2 py-0.5 rounded ${
                          sync.status === 'completed'
                            ? 'bg-green-500/20 text-green-400'
                            : sync.status === 'failed'
                              ? 'bg-red-500/20 text-red-400'
                              : sync.status === 'running'
                                ? 'bg-yellow-500/20 text-yellow-400'
                                : 'bg-gray-500/20 text-gray-400'
                        }`}
                      >
                        {sync.status.toUpperCase()}
                      </span>
                      <span className="text-xs text-text-muted font-theme-data">
                        {new Date(sync.started_at).toLocaleString()}
                      </span>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs font-theme-data">
                      <div>
                        <span className="text-text-muted">Items:</span>
                        <span className="ml-1 text-text">
                          {sync.items_synced || sync.items_processed || 0}
                        </span>
                      </div>
                      <div>
                        <span className="text-text-muted">Failed:</span>
                        <span className="ml-1 text-text">{sync.items_failed || 0}</span>
                      </div>
                      <div>
                        <span className="text-text-muted">Duration:</span>
                        <span className="ml-1 text-text">
                          {sync.duration_seconds ? `${sync.duration_seconds}s` : '-'}
                        </span>
                      </div>
                    </div>
                    {(sync.error || sync.error_message) && (
                      <div className="mt-2 p-2 bg-red-500/10 border border-red-500/30 rounded text-xs text-red-400 font-theme-data">
                        {sync.error || sync.error_message}
                      </div>
                    )}
                  </div>
                ))
              ) : (
                <div className="text-center py-8 text-text-muted font-theme-data">
                  No sync history yet
                </div>
              )}
            </div>
          )}

          {activeTab === 'config' && (
            <div className="space-y-4">
              <h3 className="text-sm font-theme-data font-bold text-text mb-3">CONFIGURATION</h3>
              <div className="p-4 bg-bg rounded-lg border border-border">
                <pre className="text-sm font-theme-data text-text whitespace-pre-wrap">
                  {JSON.stringify(details.config || {}, null, 2)}
                </pre>
              </div>
              <div className="p-4 bg-bg rounded-lg border border-border">
                <h4 className="text-xs font-theme-data font-bold text-text-muted mb-2">METADATA</h4>
                <div className="grid grid-cols-2 gap-2 text-xs font-theme-data">
                  <div>
                    <span className="text-text-muted">ID:</span>
                    <span className="ml-2 text-text">{details.id}</span>
                  </div>
                  <div>
                    <span className="text-text-muted">Job ID:</span>
                    <span className="ml-2 text-text">{details.job_id}</span>
                  </div>
                  {details.created_at && (
                    <div>
                      <span className="text-text-muted">Created:</span>
                      <span className="ml-2 text-text">
                        {new Date(details.created_at).toLocaleString()}
                      </span>
                    </div>
                  )}
                  {details.updated_at && (
                    <div>
                      <span className="text-text-muted">Updated:</span>
                      <span className="ml-2 text-text">
                        {new Date(details.updated_at).toLocaleString()}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ConnectorsPage() {
  const { showToast } = useToastContext();
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [stats, setStats] = useState<SchedulerStats | null>(null);
  const [history, setHistory] = useState<SyncHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingConnector, setEditingConnector] = useState<Connector | null>(null);
  const [viewingConnectorId, setViewingConnectorId] = useState<string | null>(null);
  const [syncingConnectors, setSyncingConnectors] = useState<Set<string>>(new Set());

  // Real-time connector sync updates via WebSocket
  const {
    isConnected: wsConnected,
    syncs: activeSyncs,
    recentDocuments,
    rateLimitWarnings,
  } = useConnectorWebSocket({
    enabled: true,
    autoReconnect: true,
    onSyncUpdate: useCallback(
      (sync: ConnectorSyncState) => {
        if (sync.status === 'completed' || sync.status === 'failed') {
          showToast(
            `Sync ${sync.connector_name}: ${sync.status}`,
            sync.status === 'completed' ? 'success' : 'error',
          );
        }
      },
      [showToast],
    ),
  });

  // Merge WebSocket sync progress into connector list for real-time updates
  const connectorsWithLiveSync = useMemo(() => {
    if (activeSyncs.length === 0) return connectors;
    return connectors.map((c) => {
      const liveSync = activeSyncs.find((s) => s.connector_id === c.id);
      if (liveSync && liveSync.status === 'running') {
        return {
          ...c,
          is_running: true,
          sync_progress: liveSync.progress / 100,
          status: 'syncing' as const,
        };
      }
      return c;
    });
  }, [connectors, activeSyncs]);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [connectorsRes, statsRes, historyRes] = await Promise.all([
        fetch(`${API_BASE_URL}/api/connectors`),
        fetch(`${API_BASE_URL}/api/connectors/scheduler/stats`),
        fetch(`${API_BASE_URL}/api/connectors/sync/history?limit=10`),
      ]);

      if (connectorsRes.ok) {
        const data = await connectorsRes.json();
        setConnectors(data.connectors || []);
      }

      if (statsRes.ok) {
        const data = await statsRes.json();
        setStats(data);
      }

      if (historyRes.ok) {
        const data = await historyRes.json();
        setHistory(data.history || []);
      }
    } catch {
      showToast('Failed to load connector data', 'error');
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleAddConnector = async (type: string, config: Record<string, string>) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/connectors`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type, config }),
      });

      if (!response.ok) throw new Error('Failed to add connector');

      showToast('Connector added successfully', 'success');
      setShowAddModal(false);
      fetchData();
    } catch {
      showToast('Failed to add connector', 'error');
    }
  };

  const handleSync = async (connectorId: string) => {
    try {
      setSyncingConnectors((prev) => new Set(prev).add(connectorId));

      const response = await fetch(`${API_BASE_URL}/api/connectors/${connectorId}/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ full_sync: false }),
      });

      if (!response.ok) throw new Error('Failed to trigger sync');

      showToast('Sync started', 'success');
      setTimeout(fetchData, 2000); // Refresh after 2s
    } catch {
      showToast('Failed to trigger sync', 'error');
    } finally {
      setSyncingConnectors((prev) => {
        const next = new Set(prev);
        next.delete(connectorId);
        return next;
      });
    }
  };

  const handleDelete = async (connectorId: string) => {
    if (!confirm('Are you sure you want to delete this connector?')) return;

    try {
      const response = await fetch(`${API_BASE_URL}/api/connectors/${connectorId}`, {
        method: 'DELETE',
      });

      if (!response.ok) throw new Error('Failed to delete connector');

      showToast('Connector deleted', 'success');
      fetchData();
    } catch {
      showToast('Failed to delete connector', 'error');
    }
  };

  const handleUpdateConnector = async (
    connectorId: string,
    updates: { schedule: Connector['schedule'] },
  ) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/connectors/${connectorId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });

      if (!response.ok) throw new Error('Failed to update connector');

      showToast('Connector updated successfully', 'success');
      setEditingConnector(null);
      fetchData();
    } catch {
      showToast('Failed to update connector', 'error');
    }
  };

  const handleCancelSync = async (syncId: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/connectors/sync/${syncId}/cancel`, {
        method: 'POST',
      });

      if (!response.ok) throw new Error('Failed to cancel sync');

      showToast('Sync cancelled', 'success');
      fetchData();
    } catch {
      showToast('Failed to cancel sync', 'error');
    }
  };

  return (
    <main className="min-h-screen bg-bg p-6">
      {/* Header */}
      <div className="max-w-7xl mx-auto mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-theme-data font-bold text-text mb-2">
              Enterprise Connectors
            </h1>
            <p className="text-text-muted">Connect and sync data from external sources</p>
            {wsConnected && (
              <div className="flex items-center gap-2 mt-1">
                <span className="w-2 h-2 rounded-full bg-[var(--accent)] animate-pulse" />
                <span className="text-xs font-theme-data text-[var(--accent)]">
                  Live sync stream connected
                  {activeSyncs.length > 0 && ` -- ${activeSyncs.length} active`}
                </span>
              </div>
            )}
          </div>

          <button
            onClick={() => setShowAddModal(true)}
            className="px-6 py-3 bg-[var(--accent)] text-bg font-theme-data font-bold hover:bg-[var(--accent)]/80 transition-colors rounded flex items-center gap-2"
          >
            <span>+</span>
            <span>Add Connector</span>
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      <PanelErrorBoundary panelName="Connector Stats">
        {stats && (
          <div className="max-w-7xl mx-auto mb-8">
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <div className="p-4 bg-surface border border-border rounded-lg">
                <div className="text-2xl font-theme-data font-bold text-text">
                  {stats.total_jobs}
                </div>
                <div className="text-xs text-text-muted font-theme-data uppercase">
                  Total Connectors
                </div>
              </div>
              <div className="p-4 bg-surface border border-border rounded-lg">
                <div className="text-2xl font-theme-data font-bold text-[var(--accent)]">
                  {stats.running_syncs}
                </div>
                <div className="text-xs text-text-muted font-theme-data uppercase">
                  Running Syncs
                </div>
              </div>
              <div className="p-4 bg-surface border border-border rounded-lg">
                <div className="text-2xl font-theme-data font-bold text-text">
                  {stats.completed_syncs}
                </div>
                <div className="text-xs text-text-muted font-theme-data uppercase">Completed</div>
              </div>
              <div className="p-4 bg-surface border border-border rounded-lg">
                <div className="text-2xl font-theme-data font-bold text-red-400">
                  {stats.failed_syncs}
                </div>
                <div className="text-xs text-text-muted font-theme-data uppercase">Failed</div>
              </div>
              <div className="p-4 bg-surface border border-border rounded-lg">
                <div className="text-2xl font-theme-data font-bold text-text">
                  {(stats.success_rate * 100).toFixed(1)}%
                </div>
                <div className="text-xs text-text-muted font-theme-data uppercase">
                  Success Rate
                </div>
              </div>
            </div>
          </div>
        )}
      </PanelErrorBoundary>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Connectors Grid */}
        <PanelErrorBoundary panelName="Connectors Grid">
          <div className="lg:col-span-2">
            <h2 className="text-lg font-theme-data font-bold text-text mb-4">Active Connectors</h2>

            {loading && (
              <div className="flex items-center justify-center py-12">
                <div className="animate-pulse text-text-muted font-theme-data">
                  Loading connectors...
                </div>
              </div>
            )}

            {!loading && connectors.length === 0 && (
              <div className="text-center py-12 bg-surface border border-border rounded-lg">
                <div className="text-4xl mb-4">🔌</div>
                <h3 className="text-lg font-theme-data font-bold text-text mb-2">
                  No connectors configured
                </h3>
                <p className="text-text-muted mb-4">
                  Add your first connector to start syncing data
                </p>
                <button
                  onClick={() => setShowAddModal(true)}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-[var(--accent)] text-bg font-theme-data font-bold hover:bg-[var(--accent)]/80 transition-colors rounded"
                >
                  Add Connector
                </button>
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {connectorsWithLiveSync.map((connector) => (
                <ConnectorCard
                  key={connector.job_id || connector.id}
                  connector={connector}
                  onSync={() => handleSync(connector.id)}
                  onCancelSync={() =>
                    connector.current_run_id && handleCancelSync(connector.current_run_id)
                  }
                  onEdit={() => setEditingConnector(connector)}
                  onDelete={() => handleDelete(connector.id)}
                  onViewDetails={() => setViewingConnectorId(connector.id)}
                  syncing={syncingConnectors.has(connector.id)}
                />
              ))}
            </div>
          </div>
        </PanelErrorBoundary>

        {/* Live Sync Activity (WebSocket) */}
        <PanelErrorBoundary panelName="Sync Activity">
          <div className="space-y-6">
            {/* Rate Limit Warnings */}
            {rateLimitWarnings.length > 0 && (
              <div>
                <h3 className="text-sm font-theme-data font-bold text-red-400 mb-2">
                  Rate Limit Warnings
                </h3>
                <div className="space-y-2">
                  {rateLimitWarnings.map((w, i) => (
                    <div
                      key={`${w.connector_id}-${i}`}
                      className="p-2 bg-red-500/10 border border-red-500/30 rounded text-xs font-theme-data text-red-400"
                    >
                      {w.message}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Recent Document Ingestion */}
            {recentDocuments.length > 0 && (
              <div>
                <h3 className="text-sm font-theme-data font-bold text-text mb-2">
                  Recent Documents ({recentDocuments.length})
                </h3>
                <div className="bg-surface border border-border rounded-lg overflow-hidden max-h-[200px] overflow-y-auto">
                  <div className="divide-y divide-border">
                    {recentDocuments.slice(0, 10).map((doc, i) => (
                      <div
                        key={`${doc.document_id}-${i}`}
                        className="px-3 py-2 flex items-center justify-between text-xs font-theme-data"
                      >
                        <span className="truncate text-text">{doc.document_name}</span>
                        <span
                          className={
                            doc.status === 'success'
                              ? 'text-green-400'
                              : doc.status === 'failed'
                                ? 'text-red-400'
                                : 'text-text-muted'
                          }
                        >
                          {doc.status.toUpperCase()}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Sync History */}
            <h2 className="text-lg font-theme-data font-bold text-text mb-4">Recent Syncs</h2>

            <div className="bg-surface border border-border rounded-lg overflow-hidden">
              {history.length === 0 ? (
                <div className="p-4 text-center text-text-muted text-sm">No sync history yet</div>
              ) : (
                <div className="divide-y divide-border">
                  {history.map((entry) => (
                    <div key={entry.run_id} className="p-3">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm font-theme-data text-text truncate">
                          {entry.job_id?.split(':').pop() || entry.run_id}
                        </span>
                        <span
                          className={`text-xs font-theme-data px-2 py-0.5 rounded ${
                            entry.status === 'completed'
                              ? 'bg-green-500/20 text-green-400'
                              : entry.status === 'failed'
                                ? 'bg-red-500/20 text-red-400'
                                : 'bg-yellow-500/20 text-yellow-400'
                          }`}
                        >
                          {entry.status.toUpperCase()}
                        </span>
                      </div>
                      <div className="flex items-center justify-between text-xs text-text-muted font-theme-data">
                        <span>{new Date(entry.started_at).toLocaleTimeString()}</span>
                        <span>{entry.items_synced} items</span>
                      </div>
                      {entry.error && (
                        <div className="mt-1 text-xs text-red-400 truncate">{entry.error}</div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </PanelErrorBoundary>
      </div>

      {/* Add Connector Modal */}
      {showAddModal && (
        <AddConnectorModal onClose={() => setShowAddModal(false)} onAdd={handleAddConnector} />
      )}

      {/* Edit Connector Modal */}
      {editingConnector && (
        <EditConnectorModal
          connector={editingConnector}
          onClose={() => setEditingConnector(null)}
          onSave={(updates) => handleUpdateConnector(editingConnector.id, updates)}
        />
      )}

      {/* Connector Details Modal */}
      {viewingConnectorId && (
        <ConnectorDetailsModal
          connectorId={viewingConnectorId}
          apiBase={API_BASE_URL}
          onClose={() => setViewingConnectorId(null)}
          onSync={() => {
            handleSync(viewingConnectorId);
            setViewingConnectorId(null);
          }}
          onCancelSync={(syncId) => {
            handleCancelSync(syncId);
            setViewingConnectorId(null);
          }}
        />
      )}
    </main>
  );
}
