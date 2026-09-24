/**
 * Knowledge Mound Analytics Dashboard.
 *
 * Displays comprehensive analytics about Knowledge Mound usage:
 * - Node statistics by type, tier, and validation status
 * - Relationship counts
 * - Confidence metrics
 * - Sharing and federation stats
 * - Real-time activity
 */

import React, { useCallback, useEffect, useState } from 'react';

interface MoundStats {
  total_nodes: number;
  nodes_by_type: Record<string, number>;
  nodes_by_tier: Record<string, number>;
  nodes_by_validation: Record<string, number>;
  total_relationships: number;
  relationships_by_type: Record<string, number>;
  average_confidence: number;
  stale_nodes_count: number;
  workspace_id?: string;
}

interface SharingStats {
  total_shared_items: number;
  items_shared_with_me: number;
  items_shared_by_me: number;
  active_grants: number;
  expired_grants: number;
}

interface FederationStats {
  registered_regions: number;
  active_schedules: number;
  total_syncs: number;
  items_pushed_today: number;
  items_pulled_today: number;
  last_sync_at?: string;
}

interface AnalyticsDashboardProps {
  /** API base URL */
  apiUrl?: string;
  /** Workspace ID to show stats for */
  workspaceId?: string;
  /** Refresh interval in ms (default: 30000) */
  refreshInterval?: number;
  /** Custom class name */
  className?: string;
}

// Simple bar chart component
const BarChart: React.FC<{
  data: Record<string, number>;
  title: string;
  maxBars?: number;
  colorScheme?: 'green' | 'cyan' | 'orange';
}> = ({ data, title, maxBars = 8, colorScheme = 'green' }) => {
  const entries = Object.entries(data)
    .sort((a, b) => b[1] - a[1])
    .slice(0, maxBars);

  if (entries.length === 0) {
    return (
      <div className="chart-container">
        <div className="chart-title">{title}</div>
        <div className="chart-empty">No data</div>
      </div>
    );
  }

  const maxValue = Math.max(...entries.map(([, v]) => v));
  const colors = { green: '#00ff00', cyan: '#00ffff', orange: '#ff6600' };
  const color = colors[colorScheme];

  return (
    <div className="chart-container" style={{ marginBottom: '20px' }}>
      <div style={{ color, fontFamily: 'monospace', marginBottom: '12px', fontSize: '14px' }}>
        {title}
      </div>
      {entries.map(([label, value]) => (
        <div key={label} style={{ display: 'flex', alignItems: 'center', marginBottom: '8px' }}>
          <div
            style={{
              width: '100px',
              fontSize: '12px',
              color: '#888',
              fontFamily: 'monospace',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
            title={label}
          >
            {label}
          </div>
          <div style={{ flex: 1, marginLeft: '12px', height: '16px', background: '#1a1a1a' }}>
            <div
              style={{
                width: `${maxValue > 0 ? (value / maxValue) * 100 : 0}%`,
                height: '100%',
                background: color,
                transition: 'width 0.3s ease',
              }}
            />
          </div>
          <div
            style={{
              width: '50px',
              textAlign: 'right',
              color: '#aaa',
              fontFamily: 'monospace',
              fontSize: '12px',
            }}
          >
            {value.toLocaleString()}
          </div>
        </div>
      ))}
    </div>
  );
};

// Metric card component
const MetricCard: React.FC<{
  label: string;
  value: number | string;
  subtext?: string;
  color?: string;
}> = ({ label, value, subtext, color = '#00ff00' }) => (
  <div
    style={{
      background: '#0f0f0f',
      border: `1px solid ${color}40`,
      borderRadius: '4px',
      padding: '16px',
      minWidth: '150px',
    }}
  >
    <div style={{ color: '#888', fontSize: '11px', fontFamily: 'monospace', marginBottom: '4px' }}>
      {label}
    </div>
    <div style={{ color, fontSize: '28px', fontFamily: 'monospace', fontWeight: 'bold' }}>
      {typeof value === 'number' ? value.toLocaleString() : value}
    </div>
    {subtext && (
      <div style={{ color: '#666', fontSize: '10px', fontFamily: 'monospace', marginTop: '4px' }}>
        {subtext}
      </div>
    )}
  </div>
);

export const AnalyticsDashboard: React.FC<AnalyticsDashboardProps> = ({
  apiUrl = '/api/knowledge',
  workspaceId,
  refreshInterval = 30000,
  className = '',
}) => {
  const [moundStats, setMoundStats] = useState<MoundStats | null>(null);
  const [sharingStats, setSharingStats] = useState<SharingStats | null>(null);
  const [federationStats, setFederationStats] = useState<FederationStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchStats = useCallback(async () => {
    try {
      const wsParam = workspaceId ? `?workspace_id=${workspaceId}` : '';

      // Fetch all stats in parallel
      const [moundRes, sharingRes, fedRes] = await Promise.all([
        fetch(`${apiUrl}/mound/stats${wsParam}`, { credentials: 'include' }).catch((err) => {
          console.warn('[AnalyticsDashboard] Failed to fetch mound stats:', err);
          return null;
        }),
        fetch(`${apiUrl}/sharing/stats${wsParam}`, { credentials: 'include' }).catch((err) => {
          console.warn('[AnalyticsDashboard] Failed to fetch sharing stats:', err);
          return null;
        }),
        fetch(`${apiUrl}/federation/stats${wsParam}`, { credentials: 'include' }).catch((err) => {
          console.warn('[AnalyticsDashboard] Failed to fetch federation stats:', err);
          return null;
        }),
      ]);

      if (moundRes?.ok) {
        const data = await moundRes.json();
        setMoundStats(data);
      }

      if (sharingRes?.ok) {
        const data = await sharingRes.json();
        setSharingStats(data);
      }

      if (fedRes?.ok) {
        const data = await fedRes.json();
        setFederationStats(data);
      }

      setLastUpdated(new Date());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch analytics');
    } finally {
      setLoading(false);
    }
  }, [apiUrl, workspaceId]);

  // Initial fetch and polling
  useEffect(() => {
    fetchStats();
    const interval = setInterval(fetchStats, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchStats, refreshInterval]);

  if (loading && !moundStats) {
    return (
      <div
        className={`analytics-dashboard ${className}`}
        style={{ padding: '40px', textAlign: 'center' }}
      >
        <div style={{ color: '#00ff00', fontFamily: 'monospace' }}>Loading analytics...</div>
      </div>
    );
  }

  return (
    <div
      className={`analytics-dashboard ${className}`}
      style={{
        background: '#0a0a0a',
        border: '1px solid #333',
        borderRadius: '8px',
        padding: '24px',
        fontFamily: 'monospace',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '24px',
          borderBottom: '1px solid #333',
          paddingBottom: '16px',
        }}
      >
        <div>
          <div style={{ color: '#00ff00', fontSize: '18px', fontWeight: 'bold' }}>
            Knowledge Mound Analytics
          </div>
          {workspaceId && (
            <div style={{ color: '#666', fontSize: '12px', marginTop: '4px' }}>
              Workspace: {workspaceId}
            </div>
          )}
        </div>
        <div style={{ textAlign: 'right' }}>
          {lastUpdated && (
            <div style={{ color: '#666', fontSize: '11px' }}>
              Last updated: {lastUpdated.toLocaleTimeString()}
            </div>
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
              marginTop: '4px',
            }}
          >
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div
          style={{
            background: '#331111',
            border: '1px solid #ff4444',
            borderRadius: '4px',
            padding: '12px',
            marginBottom: '20px',
            color: '#ff4444',
            fontSize: '12px',
          }}
        >
          {error}
        </div>
      )}

      {/* Summary Metrics */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
          gap: '16px',
          marginBottom: '32px',
        }}
      >
        <MetricCard
          label="TOTAL NODES"
          value={moundStats?.total_nodes ?? 0}
          subtext="knowledge items"
          color="#00ff00"
        />
        <MetricCard
          label="RELATIONSHIPS"
          value={moundStats?.total_relationships ?? 0}
          subtext="connections"
          color="#00ffff"
        />
        <MetricCard
          label="AVG CONFIDENCE"
          value={
            moundStats?.average_confidence
              ? `${(moundStats.average_confidence * 100).toFixed(1)}%`
              : 'N/A'
          }
          color="#00ff00"
        />
        <MetricCard
          label="STALE NODES"
          value={moundStats?.stale_nodes_count ?? 0}
          subtext="need revalidation"
          color="#ff6600"
        />
        {sharingStats && (
          <MetricCard
            label="SHARED ITEMS"
            value={sharingStats.total_shared_items}
            subtext="active shares"
            color="#00ffff"
          />
        )}
        {federationStats && (
          <MetricCard
            label="REGIONS"
            value={federationStats.registered_regions}
            subtext="federated"
            color="#00ffff"
          />
        )}
      </div>

      {/* Charts Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
          gap: '24px',
        }}
      >
        {/* Nodes by Type */}
        {moundStats?.nodes_by_type && Object.keys(moundStats.nodes_by_type).length > 0 && (
          <div style={{ background: '#0f0f0f', padding: '16px', borderRadius: '4px' }}>
            <BarChart data={moundStats.nodes_by_type} title="NODES BY TYPE" colorScheme="green" />
          </div>
        )}

        {/* Nodes by Tier */}
        {moundStats?.nodes_by_tier && Object.keys(moundStats.nodes_by_tier).length > 0 && (
          <div style={{ background: '#0f0f0f', padding: '16px', borderRadius: '4px' }}>
            <BarChart data={moundStats.nodes_by_tier} title="NODES BY TIER" colorScheme="cyan" />
          </div>
        )}

        {/* Nodes by Validation */}
        {moundStats?.nodes_by_validation &&
          Object.keys(moundStats.nodes_by_validation).length > 0 && (
            <div style={{ background: '#0f0f0f', padding: '16px', borderRadius: '4px' }}>
              <BarChart
                data={moundStats.nodes_by_validation}
                title="VALIDATION STATUS"
                colorScheme="orange"
              />
            </div>
          )}

        {/* Relationships by Type */}
        {moundStats?.relationships_by_type &&
          Object.keys(moundStats.relationships_by_type).length > 0 && (
            <div style={{ background: '#0f0f0f', padding: '16px', borderRadius: '4px' }}>
              <BarChart
                data={moundStats.relationships_by_type}
                title="RELATIONSHIPS BY TYPE"
                colorScheme="green"
              />
            </div>
          )}
      </div>

      {/* Sharing Section */}
      {sharingStats && (
        <div style={{ marginTop: '32px' }}>
          <div style={{ color: '#00ffff', fontSize: '14px', marginBottom: '16px' }}>
            SHARING ACTIVITY
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
              gap: '12px',
            }}
          >
            <MetricCard
              label="SHARED WITH ME"
              value={sharingStats.items_shared_with_me}
              color="#00ffff"
            />
            <MetricCard
              label="SHARED BY ME"
              value={sharingStats.items_shared_by_me}
              color="#00ffff"
            />
            <MetricCard label="ACTIVE GRANTS" value={sharingStats.active_grants} color="#00ff00" />
            <MetricCard label="EXPIRED GRANTS" value={sharingStats.expired_grants} color="#666" />
          </div>
        </div>
      )}

      {/* Federation Section */}
      {federationStats && (
        <div style={{ marginTop: '32px' }}>
          <div style={{ color: '#00ffff', fontSize: '14px', marginBottom: '16px' }}>
            FEDERATION SYNC
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
              gap: '12px',
            }}
          >
            <MetricCard label="TOTAL SYNCS" value={federationStats.total_syncs} color="#00ffff" />
            <MetricCard
              label="ACTIVE SCHEDULES"
              value={federationStats.active_schedules}
              color="#00ff00"
            />
            <MetricCard
              label="PUSHED TODAY"
              value={federationStats.items_pushed_today}
              color="#00ff00"
            />
            <MetricCard
              label="PULLED TODAY"
              value={federationStats.items_pulled_today}
              color="#00ffff"
            />
          </div>
          {federationStats.last_sync_at && (
            <div style={{ color: '#666', fontSize: '11px', marginTop: '12px' }}>
              Last sync: {new Date(federationStats.last_sync_at).toLocaleString()}
            </div>
          )}
        </div>
      )}

      {/* Empty State */}
      {!moundStats && !sharingStats && !federationStats && !error && (
        <div style={{ textAlign: 'center', padding: '40px', color: '#666' }}>
          <div style={{ fontSize: '48px', marginBottom: '16px' }}>{'\u{1F4CA}'}</div>
          <div>No analytics data available</div>
          <div style={{ fontSize: '12px', marginTop: '8px' }}>
            Start adding knowledge items to see analytics
          </div>
        </div>
      )}
    </div>
  );
};

export default AnalyticsDashboard;
