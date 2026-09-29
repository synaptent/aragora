'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { UsageChart, DataPoint } from '@/components/admin/UsageChart';
import { buildHealthCheckUrl, useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';
import { useAragoraClient } from '@/hooks/useAragoraClient';

type HealthStatusValue = 'healthy' | 'degraded' | 'unhealthy' | 'ok' | 'unknown';
type HealthMode = 'demo' | 'development' | 'production' | 'unknown';

interface DatabaseHealth {
  status?: HealthStatusValue;
  latency_ms?: number;
}

interface AgentsHealth {
  status?: HealthStatusValue;
  available?: number;
  total?: number;
}

interface MemoryHealth {
  status?: HealthStatusValue;
  usage_mb?: number;
}

interface WebsocketHealth {
  status?: HealthStatusValue;
  connections?: number;
}

interface HealthStatus {
  status: HealthStatusValue;
  uptime_seconds: number;
  version: string;
  components?: {
    database?: DatabaseHealth;
    agents?: AgentsHealth;
    memory?: MemoryHealth;
    websocket?: WebsocketHealth;
  };
  agents_available?: number;
  agents_total?: number;
  websocket_connections?: number;
  database_status?: HealthStatusValue;
  timestamp: string;
  demo_mode?: boolean;
  mode?: HealthMode;
}

interface AdminStats {
  total_users: number;
  total_organizations: number;
  users_active_24h: number;
  new_users_7d: number;
  total_debates_this_month: number;
  total_api_calls_today?: number;
}

interface RecentActivity {
  id: string;
  type: 'user_signup' | 'debate_completed' | 'org_created' | 'payment_received' | 'api_error';
  description: string;
  timestamp: string;
  user_email?: string;
  org_name?: string;
}

function normalizeHealthStatus(status?: string): HealthStatusValue {
  switch (status) {
    case 'healthy':
    case 'degraded':
    case 'unhealthy':
    case 'ok':
    case 'unknown':
      return status;
    default:
      return 'unknown';
  }
}

function StatusBadge({ status }: { status: HealthStatusValue }) {
  const colors: Record<HealthStatusValue, string> = {
    healthy: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40',
    degraded: 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40',
    unhealthy: 'bg-acid-red/20 text-acid-red border-acid-red/40',
    ok: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40',
    unknown: 'bg-text-muted/10 text-text-muted border-text-muted/30',
  };

  return (
    <span className={`px-2 py-0.5 text-xs font-theme-data rounded border ${colors[status]}`}>
      {status.toUpperCase()}
    </span>
  );
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);

  if (days > 0) return `${days}d ${hours}h ${minutes}m`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function getActivityIcon(type: string): string {
  const icons: Record<string, string> = {
    user_signup: '+',
    debate_completed: '*',
    org_created: '#',
    payment_received: '$',
    api_error: '!',
  };
  return icons[type] || '>';
}

function getActivityColor(type: string): string {
  const colors: Record<string, string> = {
    user_signup: 'text-[var(--accent)]',
    debate_completed: 'text-[var(--acid-cyan)]',
    org_created: 'text-[var(--acid-yellow)]',
    payment_received: 'text-[var(--acid-magenta)]',
    api_error: 'text-acid-red',
  };
  return colors[type] || 'text-text-muted';
}

export default function AdminOverviewPage() {
  const { config: backendConfig } = useBackend();
  const { isAuthenticated } = useAuth();
  const client = useAragoraClient();

  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [recentActivity, setRecentActivity] = useState<RecentActivity[]>([]);
  const [debateChartData, setDebateChartData] = useState<DataPoint[]>([]);
  const [apiCallsChartData, setApiCallsChartData] = useState<DataPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isDemoMode, setIsDemoMode] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      // Fetch health status
      const healthRes = await fetch(buildHealthCheckUrl(backendConfig.api));
      if (healthRes.ok) {
        const healthData = await healthRes.json();
        setHealth(healthData);
        // Detect demo mode from health response or environment flag
        if (healthData.demo_mode || healthData.mode === 'demo') {
          setIsDemoMode(true);
        }
      }

      // Fetch admin stats
      if (isAuthenticated) {
        try {
          const statsData = await client.admin.stats();
          setStats(statsData.stats);
        } catch {
          // Stats may fail if not admin
        }
      }

      // Fetch recent activity from dashboard endpoint
      try {
        const activityRes = await fetch(`${backendConfig.api}/api/v1/dashboard/activity?limit=10`);
        if (activityRes.ok) {
          const activityData = await activityRes.json();
          // Transform backend activity format to frontend format
          const activities = (activityData.activities || activityData.data?.activities || []).map(
            (a: {
              id: string;
              type: string;
              title?: string;
              description?: string;
              timestamp: string;
            }) => ({
              id: a.id,
              type:
                a.type === 'email_received'
                  ? 'user_signup'
                  : a.type === 'action_completed'
                    ? 'debate_completed'
                    : a.type === 'meeting_scheduled'
                      ? 'org_created'
                      : (a.type as
                          | 'user_signup'
                          | 'debate_completed'
                          | 'org_created'
                          | 'payment_received'
                          | 'api_error'),
              description: a.title || a.description || '',
              timestamp: a.timestamp,
            }),
          );
          setRecentActivity(activities);
        }
      } catch {
        // Activity endpoint may not exist, use mock data
        setRecentActivity([
          {
            id: '1',
            type: 'user_signup',
            description: 'New user registered',
            timestamp: new Date().toISOString(),
            user_email: 'user@example.com',
          },
          {
            id: '2',
            type: 'debate_completed',
            description: 'Debate completed with consensus',
            timestamp: new Date(Date.now() - 3600000).toISOString(),
          },
          {
            id: '3',
            type: 'org_created',
            description: 'New organization created',
            timestamp: new Date(Date.now() - 7200000).toISOString(),
            org_name: 'Acme Corp',
          },
          {
            id: '4',
            type: 'payment_received',
            description: 'Payment received for Pro plan',
            timestamp: new Date(Date.now() - 10800000).toISOString(),
          },
        ]);
      }

      // Fetch chart data from analytics endpoints
      try {
        // Fetch debate trends
        const debatesRes = await fetch(
          `${backendConfig.api}/api/analytics/debates/trends?time_range=30d`,
        );
        if (debatesRes.ok) {
          const debatesData = await debatesRes.json();
          const dataPoints = debatesData.data_points || debatesData.data?.data_points || [];
          if (dataPoints.length > 0) {
            setDebateChartData(
              dataPoints.map((d: { period: string; total: number }) => ({
                label: new Date(d.period).toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                }),
                value: d.total,
                date: d.period,
              })),
            );
          }
        }

        // Fetch usage/token data for API calls chart
        const usageRes = await fetch(
          `${backendConfig.api}/api/analytics/usage/tokens?time_range=30d`,
        );
        if (usageRes.ok) {
          const usageData = await usageRes.json();
          const usagePoints = usageData.data_points || usageData.data?.data_points || [];
          if (usagePoints.length > 0) {
            setApiCallsChartData(
              usagePoints.map((d: { period: string; tokens: number; requests?: number }) => ({
                label: new Date(d.period).toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                }),
                value: d.requests || d.tokens || 0,
                date: d.period,
              })),
            );
          }
        }
      } catch {
        // Generate mock chart data if endpoints fail
        const mockDates = Array.from({ length: 30 }, (_, i) => {
          const date = new Date();
          date.setDate(date.getDate() - (29 - i));
          return date;
        });
        setDebateChartData(
          mockDates.map((d) => ({
            label: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
            value: Math.floor(Math.random() * 100) + 20,
            date: d.toISOString(),
          })),
        );
        setApiCallsChartData(
          mockDates.map((d) => ({
            label: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
            value: Math.floor(Math.random() * 5000) + 1000,
            date: d.toISOString(),
          })),
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch admin data');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, client, isAuthenticated]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60000); // Refresh every minute
    return () => clearInterval(interval);
  }, [fetchData]);

  const quickActions = [
    { label: 'Invite User', href: '/admin/users?action=invite', icon: '+', color: 'acid-green' },
    {
      label: 'Create Organization',
      href: '/admin/organizations?action=create',
      icon: '#',
      color: 'acid-cyan',
    },
    { label: 'View Audit Logs', href: '/admin/audit', icon: '!', color: 'acid-yellow' },
    { label: 'Check Billing', href: '/admin/billing', icon: '$', color: 'acid-magenta' },
  ];

  const agentsAvailable = health?.components?.agents?.available ?? health?.agents_available ?? null;
  const agentsTotal = health?.components?.agents?.total ?? health?.agents_total ?? null;
  const agentAvailability =
    agentsAvailable === null && agentsTotal === null
      ? '-'
      : `${agentsAvailable ?? '-'}/${agentsTotal ?? '-'}`;
  const websocketConnections =
    health?.components?.websocket?.connections ?? health?.websocket_connections ?? null;
  const databaseStatus = normalizeHealthStatus(
    health?.components?.database?.status ?? health?.database_status,
  );

  return (
    <AdminLayout
      title="Admin Overview"
      description="System health, usage metrics, and recent activity at a glance."
      actions={
        <button
          onClick={fetchData}
          disabled={loading}
          className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
        >
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      }
    >
      {error && (
        <div className="card p-4 mb-6 border-acid-red/40 bg-acid-red/10">
          <p className="text-acid-red font-theme-data text-sm">{error}</p>
        </div>
      )}

      {/* Quick Actions */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {quickActions.map((action) => (
          <Link
            key={action.href}
            href={action.href}
            className={`card p-4 flex items-center gap-3 hover:border-${action.color}/60 transition-colors group`}
          >
            <span
              className={`text-2xl font-theme-data text-${action.color} group-hover:scale-110 transition-transform`}
            >
              {action.icon}
            </span>
            <span className="font-theme-data text-sm text-text group-hover:text-white transition-colors">
              {action.label}
            </span>
          </Link>
        ))}
      </div>

      {/* Demo Mode Banner */}
      {isDemoMode && (
        <div className="mb-4 p-3 rounded border border-acid-yellow/30 bg-acid-yellow/5">
          <div className="flex items-center gap-2">
            <span className="font-theme-data text-sm text-[var(--acid-yellow)]">DEMO MODE</span>
            <span className="font-theme-data text-xs text-text-muted">
              Running with mock agents and sample data. Set API keys for real AI debates.
            </span>
          </div>
        </div>
      )}

      {/* Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-6">
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted mb-1">Total Users</div>
          <div className="font-theme-data text-2xl text-[var(--accent)]">
            {stats?.total_users || '-'}
          </div>
        </div>
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted mb-1">Organizations</div>
          <div className="font-theme-data text-2xl text-[var(--acid-cyan)]">
            {stats?.total_organizations || '-'}
          </div>
        </div>
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted mb-1">Active (24h)</div>
          <div className="font-theme-data text-2xl text-[var(--acid-yellow)]">
            {stats?.users_active_24h || '-'}
          </div>
        </div>
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted mb-1">New Users (7d)</div>
          <div className="font-theme-data text-2xl text-text">{stats?.new_users_7d || '-'}</div>
        </div>
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted mb-1">Debates (Month)</div>
          <div className="font-theme-data text-2xl text-[var(--acid-magenta)]">
            {stats?.total_debates_this_month || '-'}
          </div>
        </div>
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted mb-1">API Calls (Today)</div>
          <div className="font-theme-data text-2xl text-text">
            {stats?.total_api_calls_today?.toLocaleString() || '-'}
          </div>
        </div>
      </div>

      {/* System Health & Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        {/* System Health Card */}
        <div className="card p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-theme-data text-[var(--accent)]">System Health</h2>
            {health && <StatusBadge status={health.status} />}
          </div>
          {health ? (
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="font-theme-data text-sm text-text-muted">Uptime</span>
                <span className="font-theme-data text-sm text-[var(--acid-cyan)]">
                  {formatUptime(health.uptime_seconds)}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="font-theme-data text-sm text-text-muted">Version</span>
                <span className="font-theme-data text-sm text-text">{health.version}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="font-theme-data text-sm text-text-muted">Agents</span>
                <span className="font-theme-data text-sm text-[var(--accent)]">
                  {agentAvailability}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="font-theme-data text-sm text-text-muted">WebSocket</span>
                <span className="font-theme-data text-sm text-text">
                  {websocketConnections === null ? '-' : `${websocketConnections} conn`}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="font-theme-data text-sm text-text-muted">Database</span>
                <StatusBadge status={databaseStatus} />
              </div>
              <Link
                href="/admin"
                className="block mt-4 text-center font-theme-data text-xs text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
              >
                View Full System Status &gt;
              </Link>
            </div>
          ) : (
            <div className="font-theme-data text-sm text-text-muted animate-pulse">Loading...</div>
          )}
        </div>

        {/* Debates Chart */}
        <div className="lg:col-span-2">
          <UsageChart
            title="DEBATES PER DAY"
            data={debateChartData}
            type="bar"
            color="acid-green"
            loading={loading}
            height={240}
          />
        </div>
      </div>

      {/* API Calls Chart & Recent Activity Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* API Calls Chart */}
        <div className="lg:col-span-2">
          <UsageChart
            title="API CALLS PER DAY"
            data={apiCallsChartData}
            type="line"
            color="acid-cyan"
            loading={loading}
            height={240}
          />
        </div>

        {/* Recent Activity */}
        <div className="card p-6">
          <h2 className="font-theme-data text-[var(--accent)] mb-4">Recent Activity</h2>
          {recentActivity.length === 0 ? (
            <div className="font-theme-data text-sm text-text-muted">No recent activity</div>
          ) : (
            <div className="space-y-3">
              {recentActivity.slice(0, 6).map((activity) => (
                <div
                  key={activity.id}
                  className="flex items-start gap-3 pb-3 border-b border-[var(--accent)]/10 last:border-0"
                >
                  <span className={`font-theme-data text-lg ${getActivityColor(activity.type)}`}>
                    {getActivityIcon(activity.type)}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="font-theme-data text-sm text-text truncate">
                      {activity.description}
                    </div>
                    <div className="font-theme-data text-xs text-text-muted">
                      {new Date(activity.timestamp).toLocaleString()}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
          <Link
            href="/admin/audit"
            className="block mt-4 text-center font-theme-data text-xs text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
          >
            View All Activity &gt;
          </Link>
        </div>
      </div>
    </AdminLayout>
  );
}
