import { useCallback, useEffect, useRef, useState } from 'react';

export interface DebateProgressEvent {
  phase: 'assessing' | 'starting' | 'proposing' | 'critiquing' | 'voting' | 'consensus' | 'done';
  agent?: string;
  round?: number;
  totalRounds?: number;
  content?: string; // streaming proposal text
}

interface UseLandingDebateProgressOptions {
  debateId: string | null;
  wsUrl: string;
  enabled: boolean;
}

export function useLandingDebateProgress({
  debateId,
  wsUrl,
  enabled,
}: UseLandingDebateProgressOptions) {
  const [latestEvent, setLatestEvent] = useState<DebateProgressEvent | null>(null);
  const [eventCount, setEventCount] = useState(0);
  const [connected, setConnected] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const startTime = useRef<number>(Date.now());
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Elapsed timer
  useEffect(() => {
    if (!enabled) return;
    startTime.current = Date.now();
    timerRef.current = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime.current) / 1000));
    }, 1000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [enabled]);

  // WebSocket connection
  useEffect(() => {
    if (!enabled || !debateId) return;

    try {
      const ws = new WebSocket(`${wsUrl}?debate_id=${debateId}`);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => setConnected(false);
      ws.onerror = () => setConnected(false);

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const mapped = mapEventToProgress(data);
          if (mapped) {
            setLatestEvent(mapped);
            setEventCount((c) => c + 1);
          }
        } catch {
          /* ignore parse errors */
        }
      };

      return () => {
        ws.close();
      };
    } catch {
      return;
    }
  }, [enabled, debateId, wsUrl]);

  const reset = useCallback(() => {
    setLatestEvent(null);
    setEventCount(0);
    setConnected(false);
    setElapsed(0);
  }, []);

  return { latestEvent, eventCount, connected, elapsed, reset };
}

function mapEventToProgress(data: Record<string, unknown>): DebateProgressEvent | null {
  const type = data.type || data.event_type;
  switch (type) {
    case 'debate_start':
      return { phase: 'starting', agent: data.agents as string | undefined };
    case 'agent_message':
    case 'proposal':
      return {
        phase: 'proposing',
        agent: (data.agent || data.agent_name) as string | undefined,
        round: data.round as number | undefined,
        content: data.content as string | undefined,
      };
    case 'critique':
      return {
        phase: 'critiquing',
        agent: (data.agent || data.agent_name) as string | undefined,
        round: data.round as number | undefined,
      };
    case 'vote':
      return { phase: 'voting', agent: (data.agent || data.agent_name) as string | undefined };
    case 'consensus':
      return { phase: 'consensus' };
    case 'debate_end':
      return { phase: 'done' };
    default:
      return null;
  }
}
