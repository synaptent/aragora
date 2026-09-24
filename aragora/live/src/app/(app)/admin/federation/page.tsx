'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FederationOverview {
  status: string;
  connected_workspaces: number;
  online_workspaces: number;
  shared_knowledge_count: number;
  valid_consents: number;
  pending_requests: number;
  sync_health: string;
  federation_mode: string;
  timestamp: string;
}

interface ConnectedWorkspace {
  id: string;
  name: string;
  org_id: string;
  status: 'connected' | 'stale' | 'disconnected';
  is_online: boolean;
  federation_mode: string;
  last_heartbeat: string | null;
  latency_ms: number;
  shared_items: number;
  active_consents: number;
  capabilities: { agent_execution: boolean; workflow_execution: boolean; knowledge_query: boolean };
}

interface SyncEvent {
  id: string;
  type: string;
  source_workspace: string;
  target_workspace: string;
  scope?: string;
  operation?: string;
  times_used?: number;
  timestamp: string;
  last_sync?: string;
}

interface KnowledgeSharingConfig {
  types: string[];
  approval_required: boolean;
  scope: string;
  audit_enabled: boolean;
}

interface FederationConfig {
  default_policy: Record<string, unknown> | null;
  workspace_policy_count: number;
  knowledge_sharing: KnowledgeSharingConfig;
}

// ---------------------------------------------------------------------------
// Helper components
// ---------------------------------------------------------------------------

function StatusDot({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    connected: 'bg-green-500',
    healthy: 'bg-green-500',
    active: 'bg-green-500',
    stale: 'bg-yellow-500',
    degraded: 'bg-yellow-500',
    disconnected: 'bg-red-500',
    offline: 'bg-red-500',
    idle: 'bg-gray-500',
  };
  const color = colorMap[status] || 'bg-gray-500';
  return <span className={`inline-block w-2.5 h-2.5 rounded-full ${color}`} />;
}

function StatCard({
  label,
  value,
  color = 'acid-green',
}: {
  label: string;
  value: number | string;
  color?: string;
}) {
  return (
    <div className="p-4 bg-surface rounded border border-[var(--accent)]/20">
      <div className="font-theme-data text-xs text-text-muted mb-1">{label}</div>
      <div className={`font-theme-data text-2xl text-${color}`}>
        {typeof value === 'number' ? value.toLocaleString() : value}
      </div>
    </div>
  );
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return 'Never';
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return 'Just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

function eventTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    consent_active: 'Consent Active',
    consent_revoked: 'Consent Revoked',
    pending_approval: 'Pending Approval',
  };
  return labels[type] || type.replace(/_/g, ' ');
}

function eventTypeColor(type: string): string {
  if (type === 'consent_active') return 'text-green-400';
  if (type === 'consent_revoked') return 'text-red-400';
  if (type === 'pending_approval') return 'text-yellow-400';
  return 'text-text-muted';
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export default function FederationManagementPage() {
  const { config: backendConfig } = useBackend();
  const [overview, setOverview] = useState<FederationOverview | null>(null);
  const [workspaces, setWorkspaces] = useState<ConnectedWorkspace[]>([]);
  const [activity, setActivity] = useState<SyncEvent[]>([]);
  const [fedConfig, setFedConfig] = useState<FederationConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const base = backendConfig.api;
      const [statusRes, wsRes, actRes, cfgRes] = await Promise.all([
        fetch(`${base}/api/v1/federation/status`),
        fetch(`${base}/api/v1/federation/workspaces`),
        fetch(`${base}/api/v1/federation/activity`),
        fetch(`${base}/api/v1/federation/config`),
      ]);

      if (statusRes.ok) setOverview(await statusRes.json());
      if (wsRes.ok) {
        const data = await wsRes.json();
        setWorkspaces(data.workspaces || []);
      }
      if (actRes.ok) {
        const data = await actRes.json();
        setActivity(data.activity || []);
      }
      if (cfgRes.ok) setFedConfig(await cfgRes.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch federation data');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Header */}
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <div className="flex items-center gap-4">
              <Link
                href="/"
                className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
              >
                [DASHBOARD]
              </Link>
              <Link
                href="/admin"
                className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
              >
                [ADMIN]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        {/* Sub Navigation */}
        <div className="border-b border-[var(--accent)]/20 bg-surface/40">
          <div className="container mx-auto px-4">
            <div className="flex gap-4 overflow-x-auto">
              <Link
                href="/admin"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                SYSTEM
              </Link>
              <Link
                href="/admin/organizations"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                ORGANIZATIONS
              </Link>
              <Link
                href="/admin/knowledge"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                KNOWLEDGE
              </Link>
              <Link
                href="/admin/federation"
                className="px-4 py-2 font-theme-data text-sm text-[var(--accent)] border-b-2 border-[var(--accent)]"
              >
                FEDERATION
              </Link>
              <Link
                href="/admin/audit"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                AUDIT
              </Link>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          {/* Page heading */}
          <div className="mb-6 flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
                Federation Management
              </h1>
              <p className="text-text-muted font-theme-data text-sm">
                Monitor cross-workspace federation, sync activity, and knowledge sharing.
              </p>
            </div>
            <button
              onClick={fetchAll}
              disabled={loading}
              className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
            >
              {loading ? 'Refreshing...' : 'Refresh'}
            </button>
          </div>

          {error && (
            <div className="card p-4 mb-6 border-acid-red/40 bg-acid-red/10">
              <p className="text-acid-red font-theme-data text-sm">{error}</p>
            </div>
          )}

          {/* Overview Stats */}
          {overview && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              <StatCard label="Connected Workspaces" value={overview.connected_workspaces} />
              <StatCard label="Online" value={overview.online_workspaces ?? 0} color="acid-cyan" />
              <StatCard
                label="Shared Knowledge"
                value={overview.shared_knowledge_count}
                color="acid-yellow"
              />
              <div className="p-4 bg-surface rounded border border-[var(--accent)]/20">
                <div className="font-theme-data text-xs text-text-muted mb-1">Sync Health</div>
                <div className="flex items-center gap-2">
                  <StatusDot status={overview.sync_health} />
                  <span className="font-theme-data text-lg text-text capitalize">
                    {overview.sync_health}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Connected Workspaces */}
          <div className="card p-6 mb-6">
            <h2 className="font-theme-data text-[var(--accent)] mb-4">Connected Workspaces</h2>
            {workspaces.length === 0 ? (
              <p className="font-theme-data text-sm text-text-muted">
                No workspaces are currently federated. Register workspaces via the Coordination API
                to enable federation.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full font-theme-data text-sm">
                  <thead>
                    <tr className="text-left text-text-muted border-b border-[var(--accent)]/20">
                      <th className="pb-2 pr-4">Status</th>
                      <th className="pb-2 pr-4">Workspace</th>
                      <th className="pb-2 pr-4">Mode</th>
                      <th className="pb-2 pr-4">Last Sync</th>
                      <th className="pb-2 pr-4">Latency</th>
                      <th className="pb-2 pr-4">Shared Items</th>
                      <th className="pb-2">Capabilities</th>
                    </tr>
                  </thead>
                  <tbody>
                    {workspaces.map((ws) => (
                      <tr
                        key={ws.id}
                        className="border-b border-[var(--accent)]/10 hover:bg-[var(--accent)]/5 transition-colors"
                      >
                        <td className="py-3 pr-4">
                          <StatusDot status={ws.status} />
                        </td>
                        <td className="py-3 pr-4">
                          <div className="text-text">{ws.name}</div>
                          <div className="text-xs text-text-muted">{ws.id}</div>
                        </td>
                        <td className="py-3 pr-4 text-text-muted capitalize">
                          {ws.federation_mode}
                        </td>
                        <td className="py-3 pr-4 text-text-muted">
                          {formatTimestamp(ws.last_heartbeat)}
                        </td>
                        <td className="py-3 pr-4 text-text-muted">
                          {ws.latency_ms > 0 ? `${ws.latency_ms.toFixed(0)}ms` : '--'}
                        </td>
                        <td className="py-3 pr-4 text-[var(--acid-cyan)]">
                          {ws.shared_items.toLocaleString()}
                        </td>
                        <td className="py-3">
                          <div className="flex gap-1.5 flex-wrap">
                            {ws.capabilities.knowledge_query && (
                              <span className="px-1.5 py-0.5 text-xs bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/20 rounded">
                                Knowledge
                              </span>
                            )}
                            {ws.capabilities.agent_execution && (
                              <span className="px-1.5 py-0.5 text-xs bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/20 rounded">
                                Agents
                              </span>
                            )}
                            {ws.capabilities.workflow_execution && (
                              <span className="px-1.5 py-0.5 text-xs bg-acid-yellow/10 text-[var(--acid-yellow)] border border-acid-yellow/20 rounded">
                                Workflows
                              </span>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Two-column layout: Activity + Knowledge Sharing */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Sync Activity Feed */}
            <div className="card p-6">
              <h2 className="font-theme-data text-[var(--accent)] mb-4">Sync Activity</h2>
              {activity.length === 0 ? (
                <p className="font-theme-data text-sm text-text-muted">No recent sync activity.</p>
              ) : (
                <div className="space-y-3 max-h-96 overflow-y-auto pr-2">
                  {activity.map((event) => (
                    <div
                      key={event.id}
                      className="p-3 bg-bg rounded border border-[var(--accent)]/10"
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span
                          className={`font-theme-data text-xs font-bold uppercase ${eventTypeColor(event.type)}`}
                        >
                          {eventTypeLabel(event.type)}
                        </span>
                        <span className="font-theme-data text-xs text-text-muted">
                          {formatTimestamp(event.timestamp)}
                        </span>
                      </div>
                      <div className="font-theme-data text-xs text-text-muted">
                        {event.source_workspace}
                        <span className="text-[var(--accent)] mx-1">{'->'}</span>
                        {event.target_workspace}
                      </div>
                      {event.scope && (
                        <div className="font-theme-data text-xs text-text-muted mt-1">
                          Scope: <span className="text-text">{event.scope}</span>
                          {event.times_used !== undefined && (
                            <>
                              {' '}
                              | Used:{' '}
                              <span className="text-[var(--acid-cyan)]">{event.times_used}x</span>
                            </>
                          )}
                        </div>
                      )}
                      {event.operation && (
                        <div className="font-theme-data text-xs text-text-muted mt-1">
                          Operation: <span className="text-text">{event.operation}</span>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Knowledge Sharing Configuration */}
            <div className="card p-6">
              <h2 className="font-theme-data text-[var(--accent)] mb-4">Knowledge Sharing</h2>

              {fedConfig ? (
                <div className="space-y-4">
                  {/* Sharing scope */}
                  <div className="p-3 bg-bg rounded border border-[var(--accent)]/10">
                    <div className="font-theme-data text-xs text-text-muted mb-1">
                      Sharing Scope
                    </div>
                    <div className="font-theme-data text-sm text-text capitalize">
                      {fedConfig.knowledge_sharing.scope}
                    </div>
                  </div>

                  {/* Approval requirement */}
                  <div className="p-3 bg-bg rounded border border-[var(--accent)]/10">
                    <div className="font-theme-data text-xs text-text-muted mb-1">
                      Approval Required
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-block w-2.5 h-2.5 rounded-full ${
                          fedConfig.knowledge_sharing.approval_required
                            ? 'bg-yellow-500'
                            : 'bg-green-500'
                        }`}
                      />
                      <span className="font-theme-data text-sm text-text">
                        {fedConfig.knowledge_sharing.approval_required ? 'Yes' : 'No'}
                      </span>
                    </div>
                  </div>

                  {/* Audit enabled */}
                  <div className="p-3 bg-bg rounded border border-[var(--accent)]/10">
                    <div className="font-theme-data text-xs text-text-muted mb-1">
                      Audit Logging
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-block w-2.5 h-2.5 rounded-full ${
                          fedConfig.knowledge_sharing.audit_enabled ? 'bg-green-500' : 'bg-red-500'
                        }`}
                      />
                      <span className="font-theme-data text-sm text-text">
                        {fedConfig.knowledge_sharing.audit_enabled ? 'Enabled' : 'Disabled'}
                      </span>
                    </div>
                  </div>

                  {/* Shared data types */}
                  <div className="p-3 bg-bg rounded border border-[var(--accent)]/10">
                    <div className="font-theme-data text-xs text-text-muted mb-2">
                      Shared Knowledge Types
                    </div>
                    {fedConfig.knowledge_sharing.types.length > 0 ? (
                      <div className="flex gap-2 flex-wrap">
                        {fedConfig.knowledge_sharing.types.map((t) => (
                          <span
                            key={t}
                            className="px-2 py-1 text-xs font-theme-data bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/20 rounded"
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <p className="font-theme-data text-xs text-text-muted">
                        No knowledge types are currently shared.
                      </p>
                    )}
                  </div>

                  {/* Workspace policy count */}
                  <div className="p-3 bg-bg rounded border border-[var(--accent)]/10">
                    <div className="font-theme-data text-xs text-text-muted mb-1">
                      Workspace Policies
                    </div>
                    <div className="font-theme-data text-sm text-[var(--acid-cyan)]">
                      {fedConfig.workspace_policy_count} configured
                    </div>
                  </div>
                </div>
              ) : (
                <p className="font-theme-data text-sm text-text-muted">
                  Federation configuration not available.
                </p>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // FEDERATION MANAGEMENT</p>
        </footer>
      </main>
    </>
  );
}
