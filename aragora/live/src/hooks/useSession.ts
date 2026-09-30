'use client';

import { useState, useCallback, useEffect } from 'react';
import { API_BASE_URL } from '@/config';
import { useAuth } from '@/context/AuthContext';

/**
 * Session information returned from the API
 */
export interface Session {
  id: string;
  device_name: string;
  ip_address: string;
  created_at: string;
  last_activity: string;
  expires_at: string;
  is_current: boolean;
}

interface SessionState {
  sessions: Session[];
  loading: boolean;
  error: string | null;
  currentSessionId: string | null;
}

interface UseSessionReturn extends SessionState {
  /** Fetch all active sessions for the current user */
  fetchSessions: () => Promise<void>;
  /** Revoke a specific session by ID */
  revokeSession: (sessionId: string) => Promise<boolean>;
  /** Revoke all sessions except the current one */
  revokeAllOtherSessions: () => Promise<boolean>;
  /** Check if a session is expired */
  isSessionExpired: (session: Session) => boolean;
  /** Get session age in human-readable format */
  getSessionAge: (session: Session) => string;
  /** Get time since last activity in human-readable format */
  getLastActivityAge: (session: Session) => string;
}

/**
 * React hook for managing user sessions
 *
 * Features:
 * - List all active sessions
 * - Revoke individual sessions
 * - Revoke all other sessions
 * - Track current session
 * - Human-readable time formatting
 *
 * @example
 * const { sessions, loading, revokeSession } = useSession();
 *
 * // Revoke a specific session
 * await revokeSession('session-id');
 *
 * // List all sessions
 * sessions.map(s => console.log(s.device_name));
 */
export function useSession(): UseSessionReturn {
  const { tokens, isAuthenticated } = useAuth();
  const [state, setState] = useState<SessionState>({
    sessions: [],
    loading: false,
    error: null,
    currentSessionId: null,
  });

  const getAuthHeaders = useCallback((): HeadersInit => {
    if (!tokens?.access_token) {
      return { 'Content-Type': 'application/json' };
    }
    return { 'Content-Type': 'application/json', Authorization: `Bearer ${tokens.access_token}` };
  }, [tokens?.access_token]);

  const fetchSessions = useCallback(async (): Promise<void> => {
    if (!isAuthenticated || !tokens?.access_token) {
      setState((prev) => ({ ...prev, sessions: [], error: 'Not authenticated' }));
      return;
    }

    setState((prev) => ({ ...prev, loading: true, error: null }));

    try {
      const response = await fetch(`${API_BASE_URL}/api/auth/sessions`, {
        method: 'GET',
        headers: getAuthHeaders(),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Failed to fetch sessions: ${response.status}`);
      }

      const data = await response.json();
      const sessions: Session[] = data.sessions || [];
      const currentSession = sessions.find((s) => s.is_current);

      setState({
        sessions,
        loading: false,
        error: null,
        currentSessionId: currentSession?.id || null,
      });
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to fetch sessions';
      setState((prev) => ({ ...prev, loading: false, error: errorMessage }));
    }
  }, [isAuthenticated, tokens?.access_token, getAuthHeaders]);

  const revokeSession = useCallback(
    async (sessionId: string): Promise<boolean> => {
      if (!isAuthenticated || !tokens?.access_token) {
        setState((prev) => ({ ...prev, error: 'Not authenticated' }));
        return false;
      }

      // Prevent revoking current session through this method
      if (sessionId === state.currentSessionId) {
        setState((prev) => ({
          ...prev,
          error: 'Cannot revoke current session. Use logout instead.',
        }));
        return false;
      }

      setState((prev) => ({ ...prev, loading: true, error: null }));

      try {
        const response = await fetch(`${API_BASE_URL}/api/auth/sessions/${sessionId}`, {
          method: 'DELETE',
          headers: getAuthHeaders(),
        });

        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || `Failed to revoke session: ${response.status}`);
        }

        // Remove the revoked session from local state
        setState((prev) => ({
          ...prev,
          sessions: prev.sessions.filter((s) => s.id !== sessionId),
          loading: false,
          error: null,
        }));

        return true;
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : 'Failed to revoke session';
        setState((prev) => ({ ...prev, loading: false, error: errorMessage }));
        return false;
      }
    },
    [isAuthenticated, tokens?.access_token, state.currentSessionId, getAuthHeaders],
  );

  const revokeAllOtherSessions = useCallback(async (): Promise<boolean> => {
    if (!isAuthenticated || !tokens?.access_token) {
      setState((prev) => ({ ...prev, error: 'Not authenticated' }));
      return false;
    }

    setState((prev) => ({ ...prev, loading: true, error: null }));

    try {
      // The endpoint revokes all sessions except the one making the request
      const response = await fetch(`${API_BASE_URL}/api/auth/sessions`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Failed to revoke sessions: ${response.status}`);
      }

      // Keep only the current session in local state
      setState((prev) => ({
        ...prev,
        sessions: prev.sessions.filter((s) => s.is_current),
        loading: false,
        error: null,
      }));

      return true;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to revoke sessions';
      setState((prev) => ({ ...prev, loading: false, error: errorMessage }));
      return false;
    }
  }, [isAuthenticated, tokens?.access_token, getAuthHeaders]);

  const isSessionExpired = useCallback((session: Session): boolean => {
    return new Date(session.expires_at) < new Date();
  }, []);

  const formatTimeAgo = useCallback((date: Date): string => {
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSeconds = Math.floor(diffMs / 1000);
    const diffMinutes = Math.floor(diffSeconds / 60);
    const diffHours = Math.floor(diffMinutes / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffDays > 0) {
      return diffDays === 1 ? '1 day ago' : `${diffDays} days ago`;
    }
    if (diffHours > 0) {
      return diffHours === 1 ? '1 hour ago' : `${diffHours} hours ago`;
    }
    if (diffMinutes > 0) {
      return diffMinutes === 1 ? '1 minute ago' : `${diffMinutes} minutes ago`;
    }
    return 'Just now';
  }, []);

  const getSessionAge = useCallback(
    (session: Session): string => {
      return formatTimeAgo(new Date(session.created_at));
    },
    [formatTimeAgo],
  );

  const getLastActivityAge = useCallback(
    (session: Session): string => {
      return formatTimeAgo(new Date(session.last_activity));
    },
    [formatTimeAgo],
  );

  // Fetch sessions when authenticated
  useEffect(() => {
    if (isAuthenticated && tokens?.access_token) {
      fetchSessions();
    }
  }, [isAuthenticated, tokens?.access_token, fetchSessions]);

  return {
    ...state,
    fetchSessions,
    revokeSession,
    revokeAllOtherSessions,
    isSessionExpired,
    getSessionAge,
    getLastActivityAge,
  };
}
