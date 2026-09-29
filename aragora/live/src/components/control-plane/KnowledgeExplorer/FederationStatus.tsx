/**
 * FederationStatus Component
 *
 * Admin panel showing the status of federated regions for multi-region
 * knowledge synchronization. Displays sync status, health, and controls.
 */

import React, { useState, useCallback } from 'react';

export type SyncMode = 'push' | 'pull' | 'bidirectional' | 'none';
export type SyncScope = 'full' | 'metadata' | 'summary';
export type RegionHealth = 'healthy' | 'degraded' | 'offline' | 'unknown';

export interface FederatedRegion {
  id: string;
  name: string;
  endpointUrl: string;
  mode: SyncMode;
  scope: SyncScope;
  enabled: boolean;
  health: RegionHealth;
  lastSyncAt?: Date;
  lastSyncError?: string;
  nodesSynced?: number;
  pendingSync?: number;
}

export interface FederationStatusProps {
  /** List of federated regions */
  regions: FederatedRegion[];
  /** Whether the panel is loading */
  isLoading?: boolean;
  /** Current user is admin */
  isAdmin?: boolean;
  /** Callback to trigger sync with a region */
  onSync?: (regionId: string, direction: 'push' | 'pull') => void;
  /** Callback to toggle region enabled state */
  onToggleEnabled?: (regionId: string, enabled: boolean) => void;
  /** Callback to add a new region */
  onAddRegion?: () => void;
  /** Callback to edit region settings */
  onEditRegion?: (regionId: string) => void;
  /** Error message */
  error?: string;
}

const healthColors: Record<RegionHealth, string> = {
  healthy: 'bg-green-500',
  degraded: 'bg-yellow-500',
  offline: 'bg-red-500',
  unknown: 'bg-gray-400',
};

const healthLabels: Record<RegionHealth, string> = {
  healthy: 'Healthy',
  degraded: 'Degraded',
  offline: 'Offline',
  unknown: 'Unknown',
};

const modeIcons: Record<SyncMode, string> = {
  push: '⬆️',
  pull: '⬇️',
  bidirectional: '🔄',
  none: '⏸️',
};

const formatDate = (date?: Date): string => {
  if (!date) return 'Never';
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
};

const formatTimeAgo = (date?: Date): string => {
  if (!date) return 'Never synced';
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
};

export const FederationStatus: React.FC<FederationStatusProps> = ({
  regions,
  isLoading = false,
  isAdmin = false,
  onSync,
  onToggleEnabled,
  onAddRegion,
  onEditRegion,
  error,
}) => {
  const [expandedRegion, setExpandedRegion] = useState<string | null>(null);
  const [syncingRegions, setSyncingRegions] = useState<Set<string>>(new Set());

  const handleSync = useCallback(
    async (regionId: string, direction: 'push' | 'pull') => {
      if (!onSync) return;
      setSyncingRegions((prev) => new Set(prev).add(regionId));
      try {
        await onSync(regionId, direction);
      } finally {
        setSyncingRegions((prev) => {
          const next = new Set(prev);
          next.delete(regionId);
          return next;
        });
      }
    },
    [onSync],
  );

  if (error) {
    return (
      <div className="p-6 text-center">
        <div className="text-red-500 mb-2">Error loading federation status</div>
        <p className="text-sm text-gray-600">{error}</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="p-6 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        <span className="ml-2 text-gray-600">Loading federation status...</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-gray-900">Federation Status</h3>
          <span className="px-1.5 py-0.5 text-xs bg-gray-100 text-gray-600 rounded">
            {regions.length} region{regions.length !== 1 ? 's' : ''}
          </span>
        </div>
        {isAdmin && onAddRegion && (
          <button
            onClick={onAddRegion}
            className="px-2 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50 rounded"
          >
            + Add Region
          </button>
        )}
      </div>

      {/* Region list */}
      <div className="flex-1 overflow-auto">
        {regions.length === 0 ? (
          <div className="p-6 text-center text-gray-500">
            No federated regions configured
            {isAdmin && (
              <p className="text-sm mt-2">Add a region to sync knowledge across deployments</p>
            )}
          </div>
        ) : (
          <ul className="divide-y divide-gray-200">
            {regions.map((region) => {
              const isExpanded = expandedRegion === region.id;
              const isSyncing = syncingRegions.has(region.id);

              return (
                <li key={region.id} className="p-4">
                  {/* Main row */}
                  <div
                    className="flex items-center gap-3 cursor-pointer"
                    onClick={() => setExpandedRegion(isExpanded ? null : region.id)}
                  >
                    {/* Health indicator */}
                    <div
                      className={`w-3 h-3 rounded-full ${healthColors[region.health]}`}
                      title={healthLabels[region.health]}
                    />

                    {/* Region info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-lg">{modeIcons[region.mode]}</span>
                        <h4 className="text-sm font-medium text-gray-900">{region.name}</h4>
                        {!region.enabled && (
                          <span className="px-1.5 py-0.5 text-xs bg-gray-100 text-gray-500 rounded">
                            Disabled
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500 truncate">{region.endpointUrl}</p>
                    </div>

                    {/* Last sync */}
                    <div className="text-right">
                      <div className="text-xs text-gray-600">
                        {formatTimeAgo(region.lastSyncAt)}
                      </div>
                      {region.nodesSynced !== undefined && (
                        <div className="text-xs text-gray-400">{region.nodesSynced} nodes</div>
                      )}
                    </div>

                    {/* Expand icon */}
                    <svg
                      className={`w-4 h-4 text-gray-400 transition-transform ${
                        isExpanded ? 'rotate-180' : ''
                      }`}
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M19 9l-7 7-7-7"
                      />
                    </svg>
                  </div>

                  {/* Expanded details */}
                  {isExpanded && (
                    <div className="mt-3 pl-6 space-y-3">
                      {/* Error message */}
                      {region.lastSyncError && (
                        <div className="p-2 bg-red-50 border border-red-100 rounded text-xs text-red-600">
                          Last error: {region.lastSyncError}
                        </div>
                      )}

                      {/* Details grid */}
                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div>
                          <span className="text-gray-500">Mode:</span>{' '}
                          <span className="font-medium capitalize">{region.mode}</span>
                        </div>
                        <div>
                          <span className="text-gray-500">Scope:</span>{' '}
                          <span className="font-medium capitalize">{region.scope}</span>
                        </div>
                        <div>
                          <span className="text-gray-500">Last sync:</span>{' '}
                          <span className="font-medium">{formatDate(region.lastSyncAt)}</span>
                        </div>
                        {region.pendingSync !== undefined && (
                          <div>
                            <span className="text-gray-500">Pending:</span>{' '}
                            <span className="font-medium">{region.pendingSync} items</span>
                          </div>
                        )}
                      </div>

                      {/* Actions */}
                      {isAdmin && (
                        <div className="flex items-center gap-2 pt-2">
                          {onSync && region.enabled && (
                            <>
                              {(region.mode === 'push' || region.mode === 'bidirectional') && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleSync(region.id, 'push');
                                  }}
                                  disabled={isSyncing}
                                  className={`
                                    px-2 py-1 text-xs font-medium rounded flex items-center gap-1
                                    ${
                                      isSyncing
                                        ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                                        : 'bg-blue-100 text-blue-700 hover:bg-blue-200'
                                    }
                                  `}
                                >
                                  {isSyncing ? <span className="animate-spin">⏳</span> : '⬆️'}
                                  Push
                                </button>
                              )}
                              {(region.mode === 'pull' || region.mode === 'bidirectional') && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleSync(region.id, 'pull');
                                  }}
                                  disabled={isSyncing}
                                  className={`
                                    px-2 py-1 text-xs font-medium rounded flex items-center gap-1
                                    ${
                                      isSyncing
                                        ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                                        : 'bg-green-100 text-green-700 hover:bg-green-200'
                                    }
                                  `}
                                >
                                  {isSyncing ? <span className="animate-spin">⏳</span> : '⬇️'}
                                  Pull
                                </button>
                              )}
                            </>
                          )}

                          {onToggleEnabled && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                onToggleEnabled(region.id, !region.enabled);
                              }}
                              className={`
                                px-2 py-1 text-xs font-medium rounded
                                ${
                                  region.enabled
                                    ? 'bg-yellow-100 text-yellow-700 hover:bg-yellow-200'
                                    : 'bg-green-100 text-green-700 hover:bg-green-200'
                                }
                              `}
                            >
                              {region.enabled ? 'Disable' : 'Enable'}
                            </button>
                          )}

                          {onEditRegion && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                onEditRegion(region.id);
                              }}
                              className="px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100 rounded"
                            >
                              Settings
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Footer summary */}
      <div className="px-4 py-2 border-t border-gray-200 bg-gray-50">
        <div className="flex items-center justify-between text-xs text-gray-600">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <span className={`w-2 h-2 rounded-full ${healthColors.healthy}`} />
              {regions.filter((r) => r.health === 'healthy').length} healthy
            </span>
            {regions.filter((r) => r.health === 'degraded').length > 0 && (
              <span className="flex items-center gap-1">
                <span className={`w-2 h-2 rounded-full ${healthColors.degraded}`} />
                {regions.filter((r) => r.health === 'degraded').length} degraded
              </span>
            )}
            {regions.filter((r) => r.health === 'offline').length > 0 && (
              <span className="flex items-center gap-1">
                <span className={`w-2 h-2 rounded-full ${healthColors.offline}`} />
                {regions.filter((r) => r.health === 'offline').length} offline
              </span>
            )}
          </div>
          <span>
            {regions.filter((r) => r.enabled).length}/{regions.length} enabled
          </span>
        </div>
      </div>
    </div>
  );
};

export default FederationStatus;
