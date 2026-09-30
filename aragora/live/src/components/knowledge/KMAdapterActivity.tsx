/**
 * KM Adapter Activity Dashboard Component.
 *
 * Displays real-time adapter activity for the Knowledge Mound:
 * - Forward sync: Data flowing from source systems to KM
 * - Reverse query: KM data being used by source systems
 * - Validation feedback: Quality improvements from debate outcomes
 *
 * Designed for the terminal-style Aragora UI.
 */

import React, { useCallback, useEffect, useState } from 'react';

interface AdapterInfo {
  name: string;
  enabled: boolean;
  priority: number;
  forward_sync_count: number;
  reverse_sync_count: number;
  last_sync?: string;
  errors: number;
}

interface AdapterStats {
  adapters: AdapterInfo[];
  total: number;
  enabled: number;
  last_sync?: string;
}

interface ActivityEvent {
  id: string;
  timestamp: string;
  type: 'forward_sync' | 'reverse_query' | 'validation' | 'semantic_search';
  source: string;
  preview?: string;
  count?: number;
  success: boolean;
}

interface KMAdapterActivityProps {
  /** API base URL */
  apiUrl?: string;
  /** WebSocket URL for real-time events */
  wsUrl?: string;
  /** Refresh interval in ms (default: 10000) */
  refreshInterval?: number;
  /** Max activity items to show */
  maxActivityItems?: number;
  /** Custom class name */
  className?: string;
}

// Activity event item
const ActivityItem: React.FC<{ event: ActivityEvent }> = ({ event }) => {
  const typeColors = {
    forward_sync: '#00ff00',
    reverse_query: '#00ffff',
    validation: '#ff6600',
    semantic_search: '#ff00ff',
  };
  const typeLabels = {
    forward_sync: 'SYNC→',
    reverse_query: '←QUERY',
    validation: '✓VALID',
    semantic_search: '🔍SEARCH',
  };

  const time = new Date(event.timestamp).toLocaleTimeString();
  const color = typeColors[event.type] || '#888';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        padding: '8px 12px',
        borderBottom: '1px solid #222',
        fontSize: '12px',
        fontFamily: 'monospace',
        opacity: event.success ? 1 : 0.6,
      }}
    >
      <span style={{ color: '#666', width: '70px' }}>{time}</span>
      <span style={{ color, width: '80px', fontWeight: 'bold' }}>{typeLabels[event.type]}</span>
      <span style={{ color: '#00ff00', width: '90px' }}>{event.source}</span>
      <span
        style={{
          color: '#888',
          flex: 1,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {event.preview || `${event.count || 0} items`}
      </span>
      {!event.success && <span style={{ color: '#ff4444', marginLeft: '8px' }}>ERROR</span>}
    </div>
  );
};

// Adapter status card
const AdapterCard: React.FC<{ adapter: AdapterInfo }> = ({ adapter }) => {
  const statusColor = adapter.enabled ? (adapter.errors > 0 ? '#ff6600' : '#00ff00') : '#666';

  return (
    <div
      style={{
        background: '#0f0f0f',
        border: `1px solid ${statusColor}40`,
        borderRadius: '4px',
        padding: '12px',
        minWidth: '180px',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '8px',
        }}
      >
        <span
          style={{
            color: statusColor,
            fontFamily: 'monospace',
            fontSize: '13px',
            fontWeight: 'bold',
          }}
        >
          {adapter.name.toUpperCase()}
        </span>
        <span
          style={{
            fontSize: '10px',
            color: adapter.enabled ? '#00ff00' : '#666',
            border: `1px solid ${adapter.enabled ? '#00ff0040' : '#66666640'}`,
            padding: '2px 6px',
            borderRadius: '2px',
          }}
        >
          {adapter.enabled ? 'ON' : 'OFF'}
        </span>
      </div>

      <div style={{ display: 'flex', gap: '16px', marginTop: '8px' }}>
        <div>
          <div style={{ color: '#666', fontSize: '10px', fontFamily: 'monospace' }}>FORWARD</div>
          <div style={{ color: '#00ff00', fontSize: '18px', fontFamily: 'monospace' }}>
            {adapter.forward_sync_count}
          </div>
        </div>
        <div>
          <div style={{ color: '#666', fontSize: '10px', fontFamily: 'monospace' }}>REVERSE</div>
          <div style={{ color: '#00ffff', fontSize: '18px', fontFamily: 'monospace' }}>
            {adapter.reverse_sync_count}
          </div>
        </div>
        {adapter.errors > 0 && (
          <div>
            <div style={{ color: '#666', fontSize: '10px', fontFamily: 'monospace' }}>ERRORS</div>
            <div style={{ color: '#ff4444', fontSize: '18px', fontFamily: 'monospace' }}>
              {adapter.errors}
            </div>
          </div>
        )}
      </div>

      {adapter.last_sync && (
        <div style={{ color: '#666', fontSize: '10px', marginTop: '8px' }}>
          Last: {new Date(adapter.last_sync).toLocaleTimeString()}
        </div>
      )}
    </div>
  );
};

export const KMAdapterActivity: React.FC<KMAdapterActivityProps> = ({
  apiUrl = '/api/knowledge/mound/dashboard',
  wsUrl,
  refreshInterval = 10000,
  maxActivityItems = 20,
  className = '',
}) => {
  const [stats, setStats] = useState<AdapterStats | null>(null);
  const [activity, setActivity] = useState<ActivityEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);

  // Fetch adapter stats
  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/adapters`, { credentials: 'include' });
      if (res.ok) {
        const data = await res.json();
        setStats(data.data || data);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch adapter stats');
    } finally {
      setLoading(false);
    }
  }, [apiUrl]);

  // Connect to WebSocket for real-time events
  useEffect(() => {
    if (!wsUrl) return;

    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setWsConnected(true);
      // Subscribe to KM adapter events
      ws.send(JSON.stringify({ type: 'subscribe', channel: 'km_adapter' }));
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'km_adapter_event') {
          const newEvent: ActivityEvent = {
            id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
            timestamp: new Date().toISOString(),
            type: msg.event_type,
            source: msg.source,
            preview: msg.preview,
            count: msg.count,
            success: msg.success !== false,
          };
          setActivity((prev) => [newEvent, ...prev].slice(0, maxActivityItems));
        }
      } catch {
        // Ignore invalid messages
      }
    };

    ws.onclose = () => {
      setWsConnected(false);
    };

    ws.onerror = () => {
      setWsConnected(false);
    };

    return () => {
      ws.close();
    };
  }, [wsUrl, maxActivityItems]);

  // Polling for stats
  useEffect(() => {
    fetchStats();
    const interval = setInterval(fetchStats, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchStats, refreshInterval]);

  if (loading && !stats) {
    return (
      <div className={`km-adapter-activity ${className}`} style={{ padding: '20px' }}>
        <div style={{ color: '#00ff00', fontFamily: 'monospace' }}>Loading adapter activity...</div>
      </div>
    );
  }

  return (
    <div
      className={`km-adapter-activity ${className}`}
      style={{
        background: '#0a0a0a',
        border: '1px solid #333',
        borderRadius: '8px',
        fontFamily: 'monospace',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '16px 20px',
          borderBottom: '1px solid #333',
        }}
      >
        <div>
          <div style={{ color: '#00ff00', fontSize: '16px', fontWeight: 'bold' }}>
            Adapter Activity
          </div>
          <div style={{ color: '#666', fontSize: '11px', marginTop: '2px' }}>
            {stats?.enabled || 0} of {stats?.total || 0} adapters active
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {wsUrl && (
            <span
              style={{
                fontSize: '10px',
                color: wsConnected ? '#00ff00' : '#ff4444',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              <span
                style={{
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  background: wsConnected ? '#00ff00' : '#ff4444',
                }}
              />
              {wsConnected ? 'LIVE' : 'OFFLINE'}
            </span>
          )}
          <button
            onClick={fetchStats}
            style={{
              background: 'transparent',
              border: '1px solid #333',
              color: '#00ff00',
              padding: '4px 12px',
              borderRadius: '4px',
              cursor: 'pointer',
              fontFamily: 'monospace',
              fontSize: '11px',
            }}
          >
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div
          style={{ background: '#331111', padding: '8px 16px', color: '#ff4444', fontSize: '12px' }}
        >
          {error}
        </div>
      )}

      {/* Adapter Cards */}
      {stats?.adapters && stats.adapters.length > 0 && (
        <div
          style={{
            display: 'flex',
            gap: '12px',
            padding: '16px 20px',
            overflowX: 'auto',
            borderBottom: '1px solid #333',
          }}
        >
          {stats.adapters.map((adapter) => (
            <AdapterCard key={adapter.name} adapter={adapter} />
          ))}
        </div>
      )}

      {/* Activity Feed */}
      <div>
        <div
          style={{
            padding: '12px 20px',
            color: '#666',
            fontSize: '11px',
            borderBottom: '1px solid #222',
          }}
        >
          RECENT ACTIVITY
        </div>
        {activity.length > 0 ? (
          <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
            {activity.map((event) => (
              <ActivityItem key={event.id} event={event} />
            ))}
          </div>
        ) : (
          <div
            style={{ padding: '40px 20px', textAlign: 'center', color: '#666', fontSize: '12px' }}
          >
            No recent activity
            {!wsUrl && (
              <div style={{ marginTop: '4px', fontSize: '10px' }}>
                Connect WebSocket for real-time updates
              </div>
            )}
          </div>
        )}
      </div>

      {/* Summary Stats */}
      {stats && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-around',
            padding: '12px 20px',
            borderTop: '1px solid #333',
            background: '#0f0f0f',
          }}
        >
          <div style={{ textAlign: 'center' }}>
            <div style={{ color: '#00ff00', fontSize: '20px', fontWeight: 'bold' }}>
              {stats.adapters.reduce((sum, a) => sum + a.forward_sync_count, 0)}
            </div>
            <div style={{ color: '#666', fontSize: '10px' }}>TOTAL SYNCS</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ color: '#00ffff', fontSize: '20px', fontWeight: 'bold' }}>
              {stats.adapters.reduce((sum, a) => sum + a.reverse_sync_count, 0)}
            </div>
            <div style={{ color: '#666', fontSize: '10px' }}>TOTAL QUERIES</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ color: '#ff6600', fontSize: '20px', fontWeight: 'bold' }}>
              {stats.adapters.reduce((sum, a) => sum + a.errors, 0)}
            </div>
            <div style={{ color: '#666', fontSize: '10px' }}>TOTAL ERRORS</div>
          </div>
        </div>
      )}
    </div>
  );
};

export default KMAdapterActivity;
