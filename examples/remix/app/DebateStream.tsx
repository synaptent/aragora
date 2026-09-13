import { createClient } from '@aragora/sdk';
import { useEffect, useState } from 'react';
import { connectDebateStream, type StreamEvent } from './debate-stream';

export function DebateStream({ debateId }: { debateId: string }) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setEvents([]);
    setConnected(false);
    setError(null);
    const stream = createClient({
      baseUrl: import.meta.env.VITE_ARAGORA_API_URL || 'http://localhost:8080',
      wsUrl: import.meta.env.VITE_ARAGORA_WS_URL || undefined,
    }).createWebSocket();
    return connectDebateStream(stream, debateId, {
      onEvent: event => setEvents(previous => [...previous, event].slice(-200)),
      onConnected: setConnected,
      onError: setError,
    });
  }, [debateId]);

  return (
    <div>
      <p style={{ color: connected ? '#86efac' : 'var(--text-muted)', marginBottom: '1rem' }}>
        {connected ? 'Connected' : 'Disconnected'}
      </p>
      {error && <p role="alert">{error}</p>}
      {events.length === 0 ? <p>Waiting for events...</p> : events.map((event, index) => (
        <div key={index} style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)' }}>
          <div className="event-heading">
            <strong>{event.type}{event.agent && ` (${event.agent})`}</strong>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              {new Date(event.timestamp).toLocaleTimeString()}
            </span>
          </div>
          {event.content && <p>{event.content.slice(0, 200)}{event.content.length > 200 ? '...' : ''}</p>}
        </div>
      ))}
    </div>
  );
}
