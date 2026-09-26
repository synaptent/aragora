'use client';

import { useCallback } from 'react';
import { useSWRFetch, type UseSWRFetchOptions } from './useSWRFetch';
import { API_BASE_URL } from '@/config';

// ============================================================================
// Types
// ============================================================================

export type InviteStatus = 'pending' | 'accepted' | 'expired' | 'canceled';

export interface WorkspaceInvite {
  id: string;
  workspace_id: string;
  email: string;
  role: 'owner' | 'admin' | 'member' | 'viewer';
  status: InviteStatus;
  created_by: string;
  created_at: string;
  expires_at: string;
  accepted_by?: string;
  accepted_at?: string;
}

export interface InviteListResponse {
  workspace_id: string;
  invites: WorkspaceInvite[];
  total: number;
}

export interface CreateInviteRequest {
  email: string;
  role?: 'owner' | 'admin' | 'member' | 'viewer';
  expires_in_days?: number;
}

export interface CreateInviteResponse {
  id: string;
  workspace_id: string;
  email_masked: string;
  role: string;
  status: InviteStatus;
  created_by: string;
  created_at: string;
  expires_at: string;
  invite_url: string;
}

// ============================================================================
// Hook
// ============================================================================

/**
 * Hook for managing workspace invites.
 * Provides fetching, creating, canceling, and resending invites.
 */
export function useWorkspaceInvites(
  workspaceId: string | null,
  status?: InviteStatus,
  options?: UseSWRFetchOptions<InviteListResponse>,
) {
  // Build API URL with optional status filter
  const url = workspaceId
    ? `/api/v1/workspaces/${workspaceId}/invites${status ? `?status=${status}` : ''}`
    : null;

  const result = useSWRFetch<InviteListResponse>(url, {
    refreshInterval: 30000, // Refresh every 30 seconds
    ...options,
  });

  // Create invite
  const createInvite = useCallback(
    async (data: CreateInviteRequest): Promise<CreateInviteResponse> => {
      if (!workspaceId) {
        throw new Error('Workspace ID is required');
      }

      const response = await fetch(`${API_BASE_URL}/api/v1/workspaces/${workspaceId}/invites`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(data),
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({ message: 'Failed to create invite' }));
        throw new Error(error.message || 'Failed to create invite');
      }

      // Revalidate the list
      result.mutate();

      return response.json();
    },
    [workspaceId, result],
  );

  // Cancel invite
  const cancelInvite = useCallback(
    async (inviteId: string): Promise<void> => {
      if (!workspaceId) {
        throw new Error('Workspace ID is required');
      }

      const response = await fetch(
        `${API_BASE_URL}/api/v1/workspaces/${workspaceId}/invites/${inviteId}`,
        { method: 'DELETE', credentials: 'include' },
      );

      if (!response.ok) {
        const error = await response.json().catch(() => ({ message: 'Failed to cancel invite' }));
        throw new Error(error.message || 'Failed to cancel invite');
      }

      // Revalidate the list
      result.mutate();
    },
    [workspaceId, result],
  );

  // Resend invite
  const resendInvite = useCallback(
    async (inviteId: string): Promise<void> => {
      if (!workspaceId) {
        throw new Error('Workspace ID is required');
      }

      const response = await fetch(
        `${API_BASE_URL}/api/v1/workspaces/${workspaceId}/invites/${inviteId}/resend`,
        { method: 'POST', credentials: 'include' },
      );

      if (!response.ok) {
        const error = await response.json().catch(() => ({ message: 'Failed to resend invite' }));
        throw new Error(error.message || 'Failed to resend invite');
      }

      // Revalidate the list
      result.mutate();
    },
    [workspaceId, result],
  );

  return {
    // Data
    invites: result.data?.invites ?? [],
    total: result.data?.total ?? 0,

    // State
    isLoading: result.isLoading,
    error: result.error,

    // Actions
    createInvite,
    cancelInvite,
    resendInvite,
    refresh: result.mutate,
  };
}

// ============================================================================
// Accept Invite Hook
// ============================================================================

/**
 * Hook for accepting a workspace invite.
 * Used on the invite acceptance page.
 */
export function useAcceptInvite() {
  const acceptInvite = useCallback(
    async (token: string): Promise<{ workspace_id: string; role: string }> => {
      const response = await fetch(`${API_BASE_URL}/api/v1/invites/${token}/accept`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({ message: 'Failed to accept invite' }));
        throw new Error(error.message || 'Failed to accept invite');
      }

      return response.json();
    },
    [],
  );

  return { acceptInvite };
}

export default useWorkspaceInvites;
