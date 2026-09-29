'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '@/config';
import { logger } from '@/utils/logger';
import { ApprovalPanel } from './ApprovalPanel';
import { AlertsPanel } from './AlertsPanel';
import { TriggersPanel } from './TriggersPanel';
import { MonitoringPanel } from './MonitoringPanel';
import { LearningPanel } from './LearningPanel';

type TabType = 'overview' | 'approvals' | 'alerts' | 'triggers' | 'monitoring' | 'learning';

interface AutonomousDashboardProps {
  apiBase: string;
}

interface OverviewStats {
  pending_approvals: number;
  active_alerts: number;
  scheduled_triggers: number;
  agent_count: number;
  anomalies_24h: number;
  patterns_discovered: number;
}

const TAB_CONFIG: { id: TabType; label: string; icon: string }[] = [
  { id: 'overview', label: 'Overview', icon: '📊' },
  { id: 'approvals', label: 'Approvals', icon: '✓' },
  { id: 'alerts', label: 'Alerts', icon: '⚠' },
  { id: 'triggers', label: 'Triggers', icon: '⏰' },
  { id: 'monitoring', label: 'Monitoring', icon: '📈' },
  { id: 'learning', label: 'Learning', icon: '🧠' },
];

export function AutonomousDashboard({ apiBase }: AutonomousDashboardProps) {
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [stats, setStats] = useState<OverviewStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);

  const fetchOverview = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      // Fetch stats from multiple endpoints
      const [approvals, alerts, triggers, calibrations, anomalies] = await Promise.all([
        apiFetch<{ pending: unknown[] }>(`${apiBase}/autonomous/approvals/pending`).catch(() => ({
          data: { pending: [] },
          error: null,
        })),
        apiFetch<{ alerts: unknown[] }>(`${apiBase}/autonomous/alerts/active`).catch(() => ({
          data: { alerts: [] },
          error: null,
        })),
        apiFetch<{ triggers: unknown[] }>(`${apiBase}/autonomous/triggers`).catch(() => ({
          data: { triggers: [] },
          error: null,
        })),
        apiFetch<{ calibrations: Record<string, unknown> }>(
          `${apiBase}/autonomous/learning/calibrations`,
        ).catch(() => ({ data: { calibrations: {} }, error: null })),
        apiFetch<{ anomalies: unknown[] }>(
          `${apiBase}/autonomous/monitoring/anomalies?hours=24`,
        ).catch(() => ({ data: { anomalies: [] }, error: null })),
      ]);

      setStats({
        pending_approvals: approvals.data?.pending?.length ?? 0,
        active_alerts: alerts.data?.alerts?.length ?? 0,
        scheduled_triggers: triggers.data?.triggers?.length ?? 0,
        agent_count: Object.keys(calibrations.data?.calibrations ?? {}).length,
        anomalies_24h: anomalies.data?.anomalies?.length ?? 0,
        patterns_discovered: 0, // Will be updated from learning endpoint
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch overview');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchOverview();

    // Connect to WebSocket for real-time updates
    const wsUrl = apiBase.replace('http', 'ws').replace('/api', '/ws/autonomous');
    let ws: WebSocket | null = null;

    try {
      ws = new WebSocket(wsUrl);
      ws.onopen = () => setWsConnected(true);
      ws.onclose = () => setWsConnected(false);
      ws.onerror = () => setWsConnected(false);
      ws.onmessage = () => {
        // Refresh stats on any event
        fetchOverview();
      };
    } catch {
      logger.warn('WebSocket not available');
    }

    return () => {
      ws?.close();
    };
  }, [apiBase, fetchOverview]);

  const renderOverview = () => (
    <div className="space-y-6">
      {/* Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <StatCard
          label="Pending Approvals"
          value={stats?.pending_approvals ?? 0}
          onClick={() => setActiveTab('approvals')}
          color="yellow"
        />
        <StatCard
          label="Active Alerts"
          value={stats?.active_alerts ?? 0}
          onClick={() => setActiveTab('alerts')}
          color="red"
        />
        <StatCard
          label="Triggers"
          value={stats?.scheduled_triggers ?? 0}
          onClick={() => setActiveTab('triggers')}
          color="cyan"
        />
        <StatCard
          label="Agents"
          value={stats?.agent_count ?? 0}
          onClick={() => setActiveTab('learning')}
          color="green"
        />
        <StatCard
          label="Anomalies (24h)"
          value={stats?.anomalies_24h ?? 0}
          onClick={() => setActiveTab('monitoring')}
          color="orange"
        />
        <StatCard
          label="Patterns"
          value={stats?.patterns_discovered ?? 0}
          onClick={() => setActiveTab('learning')}
          color="purple"
        />
      </div>

      {/* Quick Actions */}
      <div className="border border-white/10 bg-white/5 rounded-lg p-4">
        <h3 className="text-sm font-medium text-white/70 mb-3">Quick Actions</h3>
        <div className="flex flex-wrap gap-2">
          <QuickActionButton
            label="Run Learning Cycle"
            onClick={() => apiFetch(`${apiBase}/autonomous/learning/run`, { method: 'POST' })}
          />
          <QuickActionButton
            label="Start Scheduler"
            onClick={() => apiFetch(`${apiBase}/autonomous/triggers/start`, { method: 'POST' })}
          />
          <QuickActionButton
            label="Stop Scheduler"
            onClick={() => apiFetch(`${apiBase}/autonomous/triggers/stop`, { method: 'POST' })}
          />
        </div>
      </div>

      {/* Connection Status */}
      <div className="flex items-center gap-2 text-xs text-white/50">
        <span
          className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-[var(--accent)]' : 'bg-red-500'}`}
        />
        {wsConnected ? 'Real-time updates active' : 'Real-time updates disconnected'}
      </div>
    </div>
  );

  const renderContent = () => {
    switch (activeTab) {
      case 'overview':
        return renderOverview();
      case 'approvals':
        return <ApprovalPanel apiBase={apiBase} />;
      case 'alerts':
        return <AlertsPanel apiBase={apiBase} />;
      case 'triggers':
        return <TriggersPanel apiBase={apiBase} />;
      case 'monitoring':
        return <MonitoringPanel apiBase={apiBase} />;
      case 'learning':
        return <LearningPanel apiBase={apiBase} />;
      default:
        return null;
    }
  };

  if (error) {
    return (
      <div className="p-4 bg-red-500/10 border border-red-500/30 rounded text-red-400">
        {error}
        <button onClick={fetchOverview} className="ml-4 text-sm underline hover:no-underline">
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Autonomous Operations</h2>
        <button
          onClick={fetchOverview}
          disabled={loading}
          className="text-xs text-white/50 hover:text-white disabled:opacity-50"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-1 border-b border-white/10 pb-1">
        {TAB_CONFIG.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-3 py-1.5 text-sm rounded-t transition-colors ${
              activeTab === tab.id
                ? 'bg-white/10 text-white border-b-2 border-[var(--accent)]'
                : 'text-white/50 hover:text-white hover:bg-white/5'
            }`}
          >
            <span className="mr-1">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="min-h-[400px]">{renderContent()}</div>
    </div>
  );
}

interface StatCardProps {
  label: string;
  value: number;
  onClick?: () => void;
  color: 'yellow' | 'red' | 'cyan' | 'green' | 'orange' | 'purple';
}

function StatCard({ label, value, onClick, color }: StatCardProps) {
  const colorClasses = {
    yellow: 'border-yellow-500/30 hover:border-yellow-500/50',
    red: 'border-red-500/30 hover:border-red-500/50',
    cyan: 'border-cyan-500/30 hover:border-cyan-500/50',
    green: 'border-[var(--accent)]/30 hover:border-[var(--accent)]/50',
    orange: 'border-orange-500/30 hover:border-orange-500/50',
    purple: 'border-purple-500/30 hover:border-purple-500/50',
  };

  return (
    <button
      onClick={onClick}
      className={`p-4 bg-white/5 border rounded-lg text-left transition-colors ${colorClasses[color]}`}
    >
      <div className="text-2xl font-bold text-white">{value}</div>
      <div className="text-xs text-white/50">{label}</div>
    </button>
  );
}

interface QuickActionButtonProps {
  label: string;
  onClick: () => void;
}

function QuickActionButton({ label, onClick }: QuickActionButtonProps) {
  const [loading, setLoading] = useState(false);

  const handleClick = async () => {
    setLoading(true);
    try {
      await onClick();
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      onClick={handleClick}
      disabled={loading}
      className="px-3 py-1.5 text-xs bg-white/10 hover:bg-white/20 text-white rounded transition-colors disabled:opacity-50"
    >
      {loading ? '...' : label}
    </button>
  );
}

export default AutonomousDashboard;
