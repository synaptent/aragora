/**
 * Tests for useSession hook
 *
 * Tests cover:
 * - Initial state
 * - fetchSessions success and error cases
 * - revokeSession success and error cases
 * - revokeAllOtherSessions success and error cases
 * - Preventing revocation of current session
 * - isSessionExpired utility
 * - getSessionAge utility
 * - getLastActivityAge utility
 * - Auto-fetch on authentication
 * - Unauthenticated handling
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import { useSession, Session } from '../useSession';

// Mock dependencies
jest.mock('@/config', () => ({ API_BASE_URL: 'https://api.example.com' }));

jest.mock('@/context/AuthContext', () => ({ useAuth: jest.fn() }));

import { useAuth } from '@/context/AuthContext';
const mockUseAuth = useAuth as jest.Mock;

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Sample test data
const mockSessions: Session[] = [
  {
    id: 'session-1',
    device_name: 'Chrome on macOS',
    ip_address: '192.168.1.100',
    created_at: '2024-01-15T10:00:00Z',
    last_activity: '2024-01-15T15:30:00Z',
    expires_at: '2024-01-22T10:00:00Z',
    is_current: true,
  },
  {
    id: 'session-2',
    device_name: 'Firefox on Windows',
    ip_address: '192.168.1.101',
    created_at: '2024-01-14T08:00:00Z',
    last_activity: '2024-01-14T18:00:00Z',
    expires_at: '2024-01-21T08:00:00Z',
    is_current: false,
  },
  {
    id: 'session-3',
    device_name: 'Safari on iPhone',
    ip_address: '192.168.1.102',
    created_at: '2024-01-10T12:00:00Z',
    last_activity: '2024-01-10T14:00:00Z',
    expires_at: '2024-01-17T12:00:00Z',
    is_current: false,
  },
];

describe('useSession', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();

    // Default: authenticated user
    mockUseAuth.mockReturnValue({ isAuthenticated: true, tokens: { access_token: 'test-token' } });
  });

  describe('Initial State', () => {
    it('starts with empty sessions and not loading', async () => {
      // Prevent auto-fetch
      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ sessions: [] }) });

      const { result } = renderHook(() => useSession());

      // Initial state before fetch completes
      expect(result.current.sessions).toEqual([]);
      expect(result.current.loading).toBe(true); // loading because of auto-fetch
      expect(result.current.error).toBeNull();
    });
  });

  describe('fetchSessions', () => {
    it('fetches sessions successfully', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ sessions: mockSessions }) });

      const { result } = renderHook(() => useSession());

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.sessions).toHaveLength(3);
      expect(result.current.sessions[0].id).toBe('session-1');
      expect(result.current.currentSessionId).toBe('session-1');
      expect(result.current.error).toBeNull();
    });

    it('handles fetch error', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => ({ error: 'Server error' }),
      });

      const { result } = renderHook(() => useSession());

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.error).toBe('Server error');
      expect(result.current.sessions).toEqual([]);
    });

    it('handles network error', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));

      const { result } = renderHook(() => useSession());

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.error).toBe('Network error');
    });

    it('handles unauthenticated user', async () => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, tokens: null });

      const { result } = renderHook(() => useSession());

      // Should not call fetch for unauthenticated user
      expect(mockFetch).not.toHaveBeenCalled();
      expect(result.current.sessions).toEqual([]);
      // Error is not set initially, only when fetchSessions is called explicitly
      expect(result.current.error).toBeNull();

      // Explicitly calling fetchSessions should set error
      await act(async () => {
        await result.current.fetchSessions();
      });
      expect(result.current.error).toBe('Not authenticated');
    });

    it('includes authorization header in request', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ sessions: [] }) });

      renderHook(() => useSession());

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.example.com/api/auth/sessions',
        expect.objectContaining({
          method: 'GET',
          headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
        }),
      );
    });

    it('sets currentSessionId from is_current session', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ sessions: mockSessions }) });

      const { result } = renderHook(() => useSession());

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.currentSessionId).toBe('session-1');
    });
  });

  describe('revokeSession', () => {
    beforeEach(() => {
      // Setup with sessions already loaded
      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ sessions: mockSessions }) });
    });

    it('revokes a session successfully', async () => {
      const { result } = renderHook(() => useSession());

      await waitFor(() => {
        expect(result.current.sessions).toHaveLength(3);
      });

      // Reset mock for revoke call
      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ success: true }) });

      let success: boolean;
      await act(async () => {
        success = await result.current.revokeSession('session-2');
      });

      expect(success!).toBe(true);
      expect(result.current.sessions).toHaveLength(2);
      expect(result.current.sessions.find((s) => s.id === 'session-2')).toBeUndefined();
    });

    it('prevents revoking current session', async () => {
      const { result } = renderHook(() => useSession());

      await waitFor(() => {
        expect(result.current.currentSessionId).toBe('session-1');
      });

      let success: boolean;
      await act(async () => {
        success = await result.current.revokeSession('session-1');
      });

      expect(success!).toBe(false);
      expect(result.current.error).toBe('Cannot revoke current session. Use logout instead.');
      // Session should still be there
      expect(result.current.sessions.find((s) => s.id === 'session-1')).toBeDefined();
    });

    it('handles revoke error', async () => {
      const { result } = renderHook(() => useSession());

      await waitFor(() => {
        expect(result.current.sessions).toHaveLength(3);
      });

      mockFetch.mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => ({ error: 'Revoke failed' }),
      });

      let success: boolean;
      await act(async () => {
        success = await result.current.revokeSession('session-2');
      });

      expect(success!).toBe(false);
      expect(result.current.error).toBe('Revoke failed');
      // Session should still be there
      expect(result.current.sessions).toHaveLength(3);
    });

    it('handles unauthenticated revoke attempt', async () => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, tokens: null });

      const { result } = renderHook(() => useSession());

      let success: boolean;
      await act(async () => {
        success = await result.current.revokeSession('session-2');
      });

      expect(success!).toBe(false);
      expect(result.current.error).toBe('Not authenticated');
    });

    it('makes DELETE request to correct endpoint', async () => {
      const { result } = renderHook(() => useSession());

      await waitFor(() => {
        expect(result.current.sessions).toHaveLength(3);
      });

      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ success: true }) });

      await act(async () => {
        await result.current.revokeSession('session-2');
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.example.com/api/auth/sessions/session-2',
        expect.objectContaining({ method: 'DELETE' }),
      );
    });
  });

  describe('revokeAllOtherSessions', () => {
    beforeEach(() => {
      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ sessions: mockSessions }) });
    });

    it('revokes all other sessions successfully', async () => {
      const { result } = renderHook(() => useSession());

      await waitFor(() => {
        expect(result.current.sessions).toHaveLength(3);
      });

      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ success: true }) });

      let success: boolean;
      await act(async () => {
        success = await result.current.revokeAllOtherSessions();
      });

      expect(success!).toBe(true);
      // Only current session should remain
      expect(result.current.sessions).toHaveLength(1);
      expect(result.current.sessions[0].is_current).toBe(true);
      expect(result.current.sessions[0].id).toBe('session-1');
    });

    it('handles error when revoking all sessions', async () => {
      const { result } = renderHook(() => useSession());

      await waitFor(() => {
        expect(result.current.sessions).toHaveLength(3);
      });

      mockFetch.mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => ({ error: 'Bulk revoke failed' }),
      });

      let success: boolean;
      await act(async () => {
        success = await result.current.revokeAllOtherSessions();
      });

      expect(success!).toBe(false);
      expect(result.current.error).toBe('Bulk revoke failed');
    });

    it('handles unauthenticated bulk revoke attempt', async () => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, tokens: null });

      const { result } = renderHook(() => useSession());

      let success: boolean;
      await act(async () => {
        success = await result.current.revokeAllOtherSessions();
      });

      expect(success!).toBe(false);
      expect(result.current.error).toBe('Not authenticated');
    });

    it('makes DELETE request to sessions endpoint', async () => {
      const { result } = renderHook(() => useSession());

      await waitFor(() => {
        expect(result.current.sessions).toHaveLength(3);
      });

      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ success: true }) });

      await act(async () => {
        await result.current.revokeAllOtherSessions();
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.example.com/api/auth/sessions',
        expect.objectContaining({ method: 'DELETE' }),
      );
    });
  });

  describe('isSessionExpired', () => {
    it('returns true for expired session', () => {
      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ sessions: [] }) });

      const { result } = renderHook(() => useSession());

      const expiredSession: Session = {
        ...mockSessions[0],
        expires_at: '2020-01-01T00:00:00Z', // Past date
      };

      expect(result.current.isSessionExpired(expiredSession)).toBe(true);
    });

    it('returns false for valid session', () => {
      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ sessions: [] }) });

      const { result } = renderHook(() => useSession());

      const validSession: Session = {
        ...mockSessions[0],
        expires_at: '2099-12-31T23:59:59Z', // Future date
      };

      expect(result.current.isSessionExpired(validSession)).toBe(false);
    });
  });

  describe('getSessionAge', () => {
    beforeEach(() => {
      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ sessions: [] }) });
      // Mock Date.now to a fixed time for consistent tests
      jest.useFakeTimers();
      jest.setSystemTime(new Date('2024-01-15T16:00:00Z'));
    });

    afterEach(() => {
      jest.useRealTimers();
    });

    it('returns "Just now" for recent session', () => {
      const { result } = renderHook(() => useSession());

      const session: Session = {
        ...mockSessions[0],
        created_at: '2024-01-15T15:59:30Z', // 30 seconds ago
      };

      expect(result.current.getSessionAge(session)).toBe('Just now');
    });

    it('returns minutes for session created minutes ago', () => {
      const { result } = renderHook(() => useSession());

      const session: Session = {
        ...mockSessions[0],
        created_at: '2024-01-15T15:45:00Z', // 15 minutes ago
      };

      expect(result.current.getSessionAge(session)).toBe('15 minutes ago');
    });

    it('returns singular minute', () => {
      const { result } = renderHook(() => useSession());

      const session: Session = {
        ...mockSessions[0],
        created_at: '2024-01-15T15:59:00Z', // 1 minute ago
      };

      expect(result.current.getSessionAge(session)).toBe('1 minute ago');
    });

    it('returns hours for session created hours ago', () => {
      const { result } = renderHook(() => useSession());

      const session: Session = {
        ...mockSessions[0],
        created_at: '2024-01-15T10:00:00Z', // 6 hours ago
      };

      expect(result.current.getSessionAge(session)).toBe('6 hours ago');
    });

    it('returns singular hour', () => {
      const { result } = renderHook(() => useSession());

      const session: Session = {
        ...mockSessions[0],
        created_at: '2024-01-15T15:00:00Z', // 1 hour ago
      };

      expect(result.current.getSessionAge(session)).toBe('1 hour ago');
    });

    it('returns days for session created days ago', () => {
      const { result } = renderHook(() => useSession());

      const session: Session = {
        ...mockSessions[0],
        created_at: '2024-01-10T16:00:00Z', // 5 days ago
      };

      expect(result.current.getSessionAge(session)).toBe('5 days ago');
    });

    it('returns singular day', () => {
      const { result } = renderHook(() => useSession());

      const session: Session = {
        ...mockSessions[0],
        created_at: '2024-01-14T16:00:00Z', // 1 day ago
      };

      expect(result.current.getSessionAge(session)).toBe('1 day ago');
    });
  });

  describe('getLastActivityAge', () => {
    beforeEach(() => {
      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ sessions: [] }) });
      jest.useFakeTimers();
      jest.setSystemTime(new Date('2024-01-15T16:00:00Z'));
    });

    afterEach(() => {
      jest.useRealTimers();
    });

    it('returns formatted last activity time', () => {
      const { result } = renderHook(() => useSession());

      const session: Session = {
        ...mockSessions[0],
        last_activity: '2024-01-15T14:00:00Z', // 2 hours ago
      };

      expect(result.current.getLastActivityAge(session)).toBe('2 hours ago');
    });
  });

  describe('Auto-fetch on authentication', () => {
    it('fetches sessions when authenticated', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ sessions: mockSessions }) });

      renderHook(() => useSession());

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          'https://api.example.com/api/auth/sessions',
          expect.any(Object),
        );
      });
    });

    it('does not fetch when not authenticated', () => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, tokens: null });

      renderHook(() => useSession());

      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('refetches when tokens change', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ sessions: mockSessions }) });

      const { rerender } = renderHook(() => useSession());

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledTimes(1);
      });

      // Update tokens
      mockUseAuth.mockReturnValue({ isAuthenticated: true, tokens: { access_token: 'new-token' } });

      rerender();

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledTimes(2);
      });
    });
  });

  describe('Error handling edge cases', () => {
    it('handles JSON parse error on fetch', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => {
          throw new Error('Invalid JSON');
        },
      });

      const { result } = renderHook(() => useSession());

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.error).toBe('Failed to fetch sessions: 500');
    });

    it('handles JSON parse error on revoke', async () => {
      // First, load sessions
      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ sessions: mockSessions }) });

      const { result } = renderHook(() => useSession());

      await waitFor(() => {
        expect(result.current.sessions).toHaveLength(3);
      });

      // Then fail revoke with JSON error
      mockFetch.mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => {
          throw new Error('Invalid JSON');
        },
      });

      let success: boolean;
      await act(async () => {
        success = await result.current.revokeSession('session-2');
      });

      expect(success!).toBe(false);
      expect(result.current.error).toBe('Failed to revoke session: 500');
    });

    it('handles missing sessions array in response', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => ({}), // No sessions array
      });

      const { result } = renderHook(() => useSession());

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.sessions).toEqual([]);
      expect(result.current.error).toBeNull();
    });
  });
});
