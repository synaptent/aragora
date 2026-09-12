'use client';

/**
 * Sharing hook for cross-workspace knowledge sharing.
 *
 * Provides:
 * - Share items with workspaces/users
 * - View items shared with me
 * - Revoke shares
 */

import { useState, useCallback } from 'react';
import { useApi } from './useApi';
import { useBackend } from '@/components/BackendSelector';
import type { SharedItem } from '@/components/control-plane/KnowledgeExplorer/SharedWithMeTab';

export interface ShareRequest {
  itemId: string;
  toWorkspaceId?: string;
  toUserId?: string;
  permissions: string[];
  expiresAt?: Date;
}

export interface ShareResponse {
  grantId: string;
  itemId: string;
  granteeType: string;
  granteeId: string;
  permissions: string[];
  sharedAt: Date;
  expiresAt?: Date;
}

export interface UseSharingOptions {
  /** Current workspace ID */
  workspaceId?: string;
}

export interface UseSharingReturn {
  // State
  sharedItems: SharedItem[];
  isLoading: boolean;
  error: string | null;

  // Operations
  shareItem: (request: ShareRequest) => Promise<ShareResponse>;
  loadSharedWithMe: (limit?: number) => Promise<SharedItem[]>;
  acceptSharedItem: (itemId: string) => Promise<void>;
  declineSharedItem: (itemId: string) => Promise<void>;
  revokeShare: (itemId: string, granteeId: string) => Promise<void>;
  getMyShares: (itemId: string) => Promise<ShareResponse[]>;
}

export function useSharing(options: UseSharingOptions = {}): UseSharingReturn {
  const { workspaceId = 'default' } = options;
  const { config: backendConfig } = useBackend();
  const api = useApi(backendConfig?.api);
  const [sharedItems, setSharedItems] = useState<SharedItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const shareItem = useCallback(
    async (shareRequest: ShareRequest): Promise<ShareResponse> => {
      setIsLoading(true);
      setError(null);
      try {
        const response = (await api.post('/api/knowledge/mound/share', {
          item_id: shareRequest.itemId,
          from_workspace_id: workspaceId,
          to_workspace_id: shareRequest.toWorkspaceId,
          to_user_id: shareRequest.toUserId,
          permissions: shareRequest.permissions,
          expires_at: shareRequest.expiresAt?.toISOString(),
        })) as ShareResponse;
        return {
          ...response,
          sharedAt: new Date(response.sharedAt),
          expiresAt: response.expiresAt ? new Date(response.expiresAt) : undefined,
        };
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to share item';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api, workspaceId],
  );

  const loadSharedWithMe = useCallback(
    async (limit = 50): Promise<SharedItem[]> => {
      setIsLoading(true);
      setError(null);
      try {
        const response = (await api.get(
          `/api/knowledge/mound/shared-with-me?workspace_id=${workspaceId}&limit=${limit}`,
        )) as { items: SharedItem[] };
        const items = response.items.map((item) => ({
          ...item,
          sharedAt: new Date(item.sharedAt),
          expiresAt: item.expiresAt ? new Date(item.expiresAt) : undefined,
        }));
        setSharedItems(items);
        return items;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to load shared items';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api, workspaceId],
  );

  const acceptSharedItem = useCallback(
    async (itemId: string): Promise<void> => {
      setIsLoading(true);
      setError(null);
      try {
        await api.post(`/api/knowledge/mound/shared-with-me/${itemId}/accept`, {
          workspace_id: workspaceId,
        });
        // Refresh shared items list
        await loadSharedWithMe();
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to accept shared item';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api, workspaceId, loadSharedWithMe],
  );

  const declineSharedItem = useCallback(
    async (itemId: string): Promise<void> => {
      setIsLoading(true);
      setError(null);
      try {
        await api.post(`/api/knowledge/mound/shared-with-me/${itemId}/decline`, {
          workspace_id: workspaceId,
        });
        // Remove from local state
        setSharedItems((prev) => prev.filter((item) => item.id !== itemId));
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to decline shared item';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api, workspaceId],
  );

  const revokeShare = useCallback(
    async (itemId: string, granteeId: string): Promise<void> => {
      setIsLoading(true);
      setError(null);
      try {
        await api.delete(`/api/knowledge/mound/share/${itemId}/${granteeId}`);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to revoke share';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api],
  );

  const getMyShares = useCallback(
    async (itemId: string): Promise<ShareResponse[]> => {
      setIsLoading(true);
      setError(null);
      try {
        const response = (await api.get(`/api/knowledge/mound/nodes/${itemId}/shares`)) as {
          shares: ShareResponse[];
        };
        return response.shares.map((share) => ({
          ...share,
          sharedAt: new Date(share.sharedAt),
          expiresAt: share.expiresAt ? new Date(share.expiresAt) : undefined,
        }));
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to get shares';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api],
  );

  return {
    sharedItems,
    isLoading,
    error,
    shareItem,
    loadSharedWithMe,
    acceptSharedItem,
    declineSharedItem,
    revokeShare,
    getMyShares,
  };
}

export default useSharing;
