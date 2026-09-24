'use client';

import { useState, useCallback, useEffect } from 'react';

export interface BlockedSender {
  sender: string;
  reason: string;
  blocked_at: string;
}

export interface BlocklistState {
  blockedSenders: BlockedSender[];
  isLoading: boolean;
  error: string | null;
}

interface UseBlocklistOptions {
  apiBase: string;
  userId: string;
  authToken?: string;
}

/**
 * Hook for managing sender blocklist in email prioritization.
 * Blocked senders are filtered out in Tier 1 scoring with priority=BLOCKED.
 */
export function useBlocklist({ apiBase, userId, authToken }: UseBlocklistOptions) {
  const [state, setState] = useState<BlocklistState>({
    blockedSenders: [],
    isLoading: false,
    error: null,
  });

  const getHeaders = useCallback(() => {
    const headers: HeadersInit = { 'Content-Type': 'application/json' };
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    return headers;
  }, [authToken]);

  // Fetch the current blocklist
  const fetchBlocklist = useCallback(async () => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }));
    try {
      const response = await fetch(`${apiBase}/api/v1/inbox/blocklist?user_id=${userId}`, {
        headers: getHeaders(),
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch blocklist: ${response.statusText}`);
      }

      const data = await response.json();
      setState({ blockedSenders: data.blocked_senders || [], isLoading: false, error: null });
    } catch (err) {
      setState((prev) => ({
        ...prev,
        isLoading: false,
        error: err instanceof Error ? err.message : 'Failed to fetch blocklist',
      }));
    }
  }, [apiBase, userId, getHeaders]);

  // Check if a sender is blocked (local check)
  const isBlocked = useCallback(
    (sender: string): boolean => {
      return state.blockedSenders.some((b) => b.sender.toLowerCase() === sender.toLowerCase());
    },
    [state.blockedSenders],
  );

  // Block a sender
  const blockSender = useCallback(
    async (sender: string, reason: string = 'User blocked'): Promise<boolean> => {
      setState((prev) => ({ ...prev, isLoading: true, error: null }));
      try {
        const response = await fetch(`${apiBase}/api/v1/inbox/blocklist`, {
          method: 'POST',
          headers: getHeaders(),
          body: JSON.stringify({ user_id: userId, sender, reason }),
        });

        if (!response.ok) {
          throw new Error(`Failed to block sender: ${response.statusText}`);
        }

        const data = await response.json();

        // Optimistic update
        setState((prev) => ({
          ...prev,
          blockedSenders: [
            ...prev.blockedSenders,
            { sender, reason, blocked_at: data.blocked_at || new Date().toISOString() },
          ],
          isLoading: false,
          error: null,
        }));

        return true;
      } catch (err) {
        setState((prev) => ({
          ...prev,
          isLoading: false,
          error: err instanceof Error ? err.message : 'Failed to block sender',
        }));
        return false;
      }
    },
    [apiBase, userId, getHeaders],
  );

  // Unblock a sender
  const unblockSender = useCallback(
    async (sender: string): Promise<boolean> => {
      setState((prev) => ({ ...prev, isLoading: true, error: null }));
      try {
        const encodedSender = encodeURIComponent(sender);
        const response = await fetch(
          `${apiBase}/api/v1/inbox/blocklist/${encodedSender}?user_id=${userId}`,
          { method: 'DELETE', headers: getHeaders() },
        );

        if (!response.ok) {
          throw new Error(`Failed to unblock sender: ${response.statusText}`);
        }

        // Optimistic update
        setState((prev) => ({
          ...prev,
          blockedSenders: prev.blockedSenders.filter(
            (b) => b.sender.toLowerCase() !== sender.toLowerCase(),
          ),
          isLoading: false,
          error: null,
        }));

        return true;
      } catch (err) {
        setState((prev) => ({
          ...prev,
          isLoading: false,
          error: err instanceof Error ? err.message : 'Failed to unblock sender',
        }));
        return false;
      }
    },
    [apiBase, userId, getHeaders],
  );

  // Clear error
  const clearError = useCallback(() => {
    setState((prev) => ({ ...prev, error: null }));
  }, []);

  // Fetch blocklist on mount
  useEffect(() => {
    fetchBlocklist();
  }, [fetchBlocklist]);

  return {
    ...state,
    isBlocked,
    blockSender,
    unblockSender,
    refreshBlocklist: fetchBlocklist,
    clearError,
  };
}

export default useBlocklist;
