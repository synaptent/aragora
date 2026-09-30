'use client';

/**
 * Visibility hook for managing knowledge item visibility levels.
 *
 * Provides:
 * - Get/set visibility for items
 * - Manage access grants
 * - Query discoverable items
 */

import { useState, useCallback } from 'react';
import { useApi } from './useApi';
import { useBackend } from '@/components/BackendSelector';
import type { VisibilityLevel } from '@/components/control-plane/KnowledgeExplorer/VisibilitySelector';
import type { AccessGrant } from '@/components/control-plane/KnowledgeExplorer/AccessGrantsList';

type GranteeType = 'user' | 'workspace' | 'organization' | 'role';

export interface VisibilityInfo {
  visibility: VisibilityLevel;
  setBy?: string;
  isDiscoverable: boolean;
  grants: AccessGrant[];
}

export interface UseVisibilityOptions {
  /** Workspace ID */
  workspaceId?: string;
}

export interface UseVisibilityReturn {
  // State
  isLoading: boolean;
  error: string | null;

  // Operations
  getVisibility: (itemId: string) => Promise<VisibilityInfo>;
  setVisibility: (itemId: string, visibility: VisibilityLevel) => Promise<void>;
  getGrants: (itemId: string) => Promise<AccessGrant[]>;
  addGrant: (
    itemId: string,
    granteeType: 'user' | 'workspace' | 'organization' | 'role',
    granteeId: string,
    permissions: string[],
    expiresAt?: Date,
  ) => Promise<AccessGrant>;
  revokeGrant: (itemId: string, grantId: string) => Promise<void>;
}

export function useVisibility(options: UseVisibilityOptions = {}): UseVisibilityReturn {
  const { workspaceId = 'default' } = options;
  const { config: backendConfig } = useBackend();
  const api = useApi(backendConfig?.api);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const getVisibility = useCallback(
    async (itemId: string): Promise<VisibilityInfo> => {
      setIsLoading(true);
      setError(null);
      try {
        const response = await api.get(`/api/knowledge/mound/nodes/${itemId}/visibility`);
        return response as VisibilityInfo;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to get visibility';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api],
  );

  const setVisibility = useCallback(
    async (itemId: string, visibility: VisibilityLevel): Promise<void> => {
      setIsLoading(true);
      setError(null);
      try {
        await api.put(`/api/knowledge/mound/nodes/${itemId}/visibility`, {
          visibility,
          workspace_id: workspaceId,
        });
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to set visibility';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api, workspaceId],
  );

  const getGrants = useCallback(
    async (itemId: string): Promise<AccessGrant[]> => {
      setIsLoading(true);
      setError(null);
      try {
        const response = await api.get(`/api/knowledge/mound/nodes/${itemId}/grants`);
        return (response as { grants: AccessGrant[] }).grants;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to get grants';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api],
  );

  const addGrant = useCallback(
    async (
      itemId: string,
      granteeType: GranteeType,
      granteeId: string,
      permissions: string[],
      expiresAt?: Date,
    ): Promise<AccessGrant> => {
      setIsLoading(true);
      setError(null);
      try {
        const response = await api.post(`/api/knowledge/mound/nodes/${itemId}/grants`, {
          grantee_type: granteeType,
          grantee_id: granteeId,
          permissions,
          expires_at: expiresAt?.toISOString(),
          workspace_id: workspaceId,
        });
        return response as AccessGrant;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to add grant';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api, workspaceId],
  );

  const revokeGrant = useCallback(
    async (itemId: string, grantId: string): Promise<void> => {
      setIsLoading(true);
      setError(null);
      try {
        await api.delete(`/api/knowledge/mound/nodes/${itemId}/grants/${grantId}`);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to revoke grant';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api],
  );

  return { isLoading, error, getVisibility, setVisibility, getGrants, addGrant, revokeGrant };
}

export default useVisibility;
