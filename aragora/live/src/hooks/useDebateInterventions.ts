'use client';

import { useState, useCallback, useRef } from 'react';
import { API_BASE_URL } from '@/config';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface InterventionEntry {
  type: string;
  timestamp: number;
  user_id: string | null;
  message: string | null;
  target_agent: string | null;
  source: string | null;
  metadata: Record<string, unknown>;
}

export interface InterventionLog {
  debate_id: string;
  state: string;
  entry_count: number;
  entries: InterventionEntry[];
}

export interface InterventionResult {
  success: boolean;
  debate_id: string;
  state?: string;
  intervention?: InterventionEntry;
}

interface UseDebateInterventionsReturn {
  /** Whether any intervention request is currently in flight */
  loading: boolean;
  /** Last error message, or null */
  error: string | null;
  /** The most recent intervention log fetched from the server */
  log: InterventionLog | null;
  /** Current debate state as reported by the last intervention */
  debateState: string | null;

  /** Pause a running debate */
  pause: () => Promise<InterventionResult | null>;
  /** Resume a paused debate */
  resume: () => Promise<InterventionResult | null>;
  /** Send a nudge to the debate */
  nudge: (message: string, targetAgent?: string) => Promise<InterventionResult | null>;
  /** Inject a challenge into the debate */
  challenge: (challengeText: string) => Promise<InterventionResult | null>;
  /** Inject evidence into the debate */
  injectEvidence: (evidence: string, source?: string) => Promise<InterventionResult | null>;
  /** Refresh the intervention log from the server */
  refreshLog: () => Promise<void>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getStoredAccessToken(): string | null {
  if (typeof window === 'undefined') return null;
  const stored = localStorage.getItem('aragora_tokens');
  if (!stored) return null;
  try {
    return (JSON.parse(stored) as { access_token?: string }).access_token || null;
  } catch {
    return null;
  }
}

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const token = getStoredAccessToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * React hook for debate intervention controls.
 *
 * Provides methods to pause, resume, nudge, challenge, and inject evidence
 * into a live debate, plus the ability to fetch the intervention log.
 *
 * @param debateId - The ID of the debate to manage
 *
 * @example
 * ```tsx
 * function DebateControls({ debateId }: { debateId: string }) {
 *   const {
 *     pause, resume, nudge, challenge, injectEvidence,
 *     loading, error, debateState, refreshLog, log,
 *   } = useDebateInterventions(debateId);
 *
 *   return (
 *     <div>
 *       <button onClick={pause} disabled={loading}>Pause</button>
 *       <button onClick={resume} disabled={loading}>Resume</button>
 *       <button onClick={() => nudge('Consider the budget impact')}>Nudge</button>
 *     </div>
 *   );
 * }
 * ```
 */
export function useDebateInterventions(debateId: string): UseDebateInterventionsReturn {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [log, setLog] = useState<InterventionLog | null>(null);
  const [debateState, setDebateState] = useState<string | null>(null);
  const inflightRef = useRef(false);

  const baseUrl = `${API_BASE_URL}/api/v1/debates/${encodeURIComponent(debateId)}`;

  // Generic POST helper
  const postIntervention = useCallback(
    async (
      endpoint: string,
      body?: Record<string, unknown>,
    ): Promise<InterventionResult | null> => {
      if (inflightRef.current) return null;
      inflightRef.current = true;
      setLoading(true);
      setError(null);

      try {
        const response = await fetch(`${baseUrl}/${endpoint}`, {
          method: 'POST',
          headers: authHeaders(),
          body: body ? JSON.stringify(body) : undefined,
        });

        const data = await response.json();

        if (!response.ok) {
          const msg = data?.error || data?.message || `Request failed (${response.status})`;
          setError(msg);
          return null;
        }

        const result = data as InterventionResult;
        if (result.state) {
          setDebateState(result.state);
        }
        return result;
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Network error';
        setError(msg);
        return null;
      } finally {
        setLoading(false);
        inflightRef.current = false;
      }
    },
    [baseUrl],
  );

  // --- Public methods ---

  const pause = useCallback(() => postIntervention('pause'), [postIntervention]);

  const resume = useCallback(() => postIntervention('resume'), [postIntervention]);

  const nudge = useCallback(
    (message: string, targetAgent?: string) =>
      postIntervention('nudge', { message, ...(targetAgent ? { target_agent: targetAgent } : {}) }),
    [postIntervention],
  );

  const challenge = useCallback(
    (challengeText: string) => postIntervention('challenge', { challenge: challengeText }),
    [postIntervention],
  );

  const injectEvidence = useCallback(
    (evidence: string, source?: string) =>
      postIntervention('inject-evidence', { evidence, ...(source ? { source } : {}) }),
    [postIntervention],
  );

  const refreshLog = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${baseUrl}/intervention-log`, { headers: authHeaders() });
      const data = await response.json();

      if (!response.ok) {
        setError(data?.error || 'Failed to fetch intervention log');
        return;
      }

      const fetched = data as InterventionLog;
      setLog(fetched);
      if (fetched.state) {
        setDebateState(fetched.state);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error');
    } finally {
      setLoading(false);
    }
  }, [baseUrl]);

  return {
    loading,
    error,
    log,
    debateState,
    pause,
    resume,
    nudge,
    challenge,
    injectEvidence,
    refreshLog,
  };
}
