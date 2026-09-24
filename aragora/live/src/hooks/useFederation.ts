'use client';

/**
 * Federation hook for multi-region knowledge synchronization.
 *
 * Provides:
 * - List federated regions
 * - Sync operations (push/pull)
 * - Region management (admin)
 */

import { useState, useCallback } from 'react';
import { useApi } from './useApi';
import { useBackend } from '@/components/BackendSelector';
import type {
  FederatedRegion,
  SyncMode,
  SyncScope,
} from '@/components/control-plane/KnowledgeExplorer/FederationStatus';

export interface SyncResult {
  nodesSynced: number;
  durationMs: number;
  errors?: string[];
}

export interface RegisterRegionRequest {
  regionId: string;
  name: string;
  endpointUrl: string;
  apiKey: string;
  mode: SyncMode;
  scope: SyncScope;
}

export interface UpdateRegionRequest {
  name?: string;
  mode?: SyncMode;
  scope?: SyncScope;
  enabled?: boolean;
}

export interface UseFederationOptions {
  /** Current workspace ID */
  workspaceId?: string;
}

export interface UseFederationReturn {
  // State
  regions: FederatedRegion[];
  isLoading: boolean;
  error: string | null;

  // Read operations
  loadRegions: () => Promise<FederatedRegion[]>;
  getRegion: (regionId: string) => Promise<FederatedRegion>;

  // Sync operations
  syncPush: (regionId: string, since?: Date) => Promise<SyncResult>;
  syncPull: (regionId: string, since?: Date) => Promise<SyncResult>;

  // Admin operations
  registerRegion: (request: RegisterRegionRequest) => Promise<FederatedRegion>;
  updateRegion: (regionId: string, updates: UpdateRegionRequest) => Promise<FederatedRegion>;
  deleteRegion: (regionId: string) => Promise<void>;
  toggleRegionEnabled: (regionId: string, enabled: boolean) => Promise<void>;
}

export function useFederation(options: UseFederationOptions = {}): UseFederationReturn {
  const { workspaceId = 'default' } = options;
  const { config: backendConfig } = useBackend();
  const api = useApi(backendConfig?.api);
  const [regions, setRegions] = useState<FederatedRegion[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadRegions = useCallback(async (): Promise<FederatedRegion[]> => {
    setIsLoading(true);
    setError(null);
    try {
      const response = (await api.get('/api/knowledge/mound/federation/regions')) as {
        regions: FederatedRegion[];
      };
      const regionList = response.regions.map((region) => ({
        ...region,
        lastSyncAt: region.lastSyncAt ? new Date(region.lastSyncAt) : undefined,
      }));
      setRegions(regionList);
      return regionList;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load regions';
      setError(message);
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, [api]);

  const getRegion = useCallback(
    async (regionId: string): Promise<FederatedRegion> => {
      setIsLoading(true);
      setError(null);
      try {
        const response = (await api.get(
          `/api/knowledge/mound/federation/regions/${regionId}`,
        )) as FederatedRegion;
        return {
          ...response,
          lastSyncAt: response.lastSyncAt ? new Date(response.lastSyncAt) : undefined,
        };
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to get region';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api],
  );

  const syncPush = useCallback(
    async (regionId: string, since?: Date): Promise<SyncResult> => {
      setIsLoading(true);
      setError(null);
      try {
        const response = (await api.post('/api/knowledge/mound/federation/sync/push', {
          region_id: regionId,
          workspace_id: workspaceId,
          since: since?.toISOString(),
        })) as SyncResult;
        // Refresh regions to update last sync time
        await loadRegions();
        return response;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to push sync';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api, workspaceId, loadRegions],
  );

  const syncPull = useCallback(
    async (regionId: string, since?: Date): Promise<SyncResult> => {
      setIsLoading(true);
      setError(null);
      try {
        const response = (await api.post('/api/knowledge/mound/federation/sync/pull', {
          region_id: regionId,
          workspace_id: workspaceId,
          since: since?.toISOString(),
        })) as SyncResult;
        // Refresh regions to update last sync time
        await loadRegions();
        return response;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to pull sync';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api, workspaceId, loadRegions],
  );

  const registerRegion = useCallback(
    async (registerRequest: RegisterRegionRequest): Promise<FederatedRegion> => {
      setIsLoading(true);
      setError(null);
      try {
        const response = (await api.post('/api/knowledge/mound/federation/regions', {
          region_id: registerRequest.regionId,
          name: registerRequest.name,
          endpoint_url: registerRequest.endpointUrl,
          api_key: registerRequest.apiKey,
          mode: registerRequest.mode,
          scope: registerRequest.scope,
        })) as FederatedRegion;
        // Refresh regions list
        await loadRegions();
        return {
          ...response,
          lastSyncAt: response.lastSyncAt ? new Date(response.lastSyncAt) : undefined,
        };
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to register region';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api, loadRegions],
  );

  const updateRegion = useCallback(
    async (regionId: string, updates: UpdateRegionRequest): Promise<FederatedRegion> => {
      setIsLoading(true);
      setError(null);
      try {
        const response = (await api.put(
          `/api/knowledge/mound/federation/regions/${regionId}`,
          updates,
        )) as FederatedRegion;
        // Refresh regions list
        await loadRegions();
        return {
          ...response,
          lastSyncAt: response.lastSyncAt ? new Date(response.lastSyncAt) : undefined,
        };
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to update region';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api, loadRegions],
  );

  const deleteRegion = useCallback(
    async (regionId: string): Promise<void> => {
      setIsLoading(true);
      setError(null);
      try {
        await api.delete(`/api/knowledge/mound/federation/regions/${regionId}`);
        // Remove from local state
        setRegions((prev) => prev.filter((r) => r.id !== regionId));
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to delete region';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api],
  );

  const toggleRegionEnabled = useCallback(
    async (regionId: string, enabled: boolean): Promise<void> => {
      await updateRegion(regionId, { enabled });
    },
    [updateRegion],
  );

  return {
    regions,
    isLoading,
    error,
    loadRegions,
    getRegion,
    syncPush,
    syncPull,
    registerRegion,
    updateRegion,
    deleteRegion,
    toggleRegionEnabled,
  };
}

export default useFederation;
