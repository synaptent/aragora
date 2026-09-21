'use client';

import { useEffect, useState } from 'react';
import { getClientSideClient } from '@/lib/aragora';
import { connectDebateStream, type StreamEvent } from '@/lib/debate-stream';

export default function DebateStream({ debateId }: { debateId: string }) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const stream = getClientSideClient().createWebSocket();
    return connectDebateStream(stream, debateId, {
      onEvent: event => setEvents(prev => [...prev.slice(-199), event]),
      onConnected: setConnected,
      onError: setError,
    });
  }, [debateId]);

  if (error) {
    return (
      <div style={{ color: '#ef4444' }}>
        Connection error: {error}
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
        <div
          style={{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            background: connected ? '#22c55e' : '#ef4444',
          }}
        />
        <span style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
          {connected ? 'Connected' : 'Disconnected'}
        </span>
      </div>

      <div className="stream-container">
        {events.length === 0 ? (
          <p style={{ color: 'var(--text-muted)' }}>Waiting for events...</p>
        ) : (
          events.map((event, idx) => (
            <div key={idx} className="stream-event">
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                <span style={{ color: 'var(--primary)', fontWeight: 500 }}>
                  {event.type}
                  {event.agent && ` (${event.agent})`}
                </span>
                <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                  {new Date(event.timestamp).toLocaleTimeString()}
                </span>
              </div>
              {event.content && (
                <p style={{ color: 'var(--text-muted)' }}>
                  {event.content.slice(0, 200)}
                  {event.content.length > 200 ? '...' : ''}
                </p>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
