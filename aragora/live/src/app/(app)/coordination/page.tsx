'use client';

import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useSWRFetch } from '@/hooks/useSWRFetch';

interface Workspace {
  workspace_id: string;
  name: string;
  status: string;
  registered_at: string;
  last_activity?: string;
}

interface Execution {
  execution_id: string;
  operation: string;
  status: string;
  source_workspace: string;
  target_workspace: string;
  created_at: string;
}

interface Consent {
  consent_id: string;
  workspace_id: string;
  scope: string;
  granted_at: string;
  expires_at?: string;
}

interface CoordinationStats {
  total_workspaces: number;
  active_executions: number;
  total_consents: number;
  federation_policies: number;
}

interface CoordinationHealth {
  healthy: boolean;
  coordinator_available: boolean;
}

const STATUS_COLORS: Record<string, string> = {
  active: 'text-[var(--accent)]',
  running: 'text-blue-400',
  pending: 'text-yellow-400',
  completed: 'text-[var(--accent)]',
  failed: 'text-red-400',
  merged: 'text-purple-400',
  archived: 'text-text-muted',
};

function statusColor(status: string): string {
  return STATUS_COLORS[status.toLowerCase()] || 'text-text-muted';
}

export default function CoordinationPage() {
  const { config } = useBackend();
  const fetchOpts = { refreshInterval: 10000, baseUrl: config.api };

  const { data: statsData, isLoading: statsLoading } = useSWRFetch<{ data: CoordinationStats }>(
    '/api/v1/coordination/stats',
    fetchOpts,
  );
  const { data: healthData } = useSWRFetch<{ data: CoordinationHealth }>(
    '/api/v1/coordination/health',
    fetchOpts,
  );
  const { data: wsData, isLoading: wsLoading } = useSWRFetch<{ data: { workspaces: Workspace[] } }>(
    '/api/v1/coordination/workspaces',
    fetchOpts,
  );
  const { data: execData } = useSWRFetch<{ data: { executions: Execution[] } }>(
    '/api/v1/coordination/executions',
    fetchOpts,
  );
  const { data: consentData } = useSWRFetch<{ data: { consents: Consent[] } }>(
    '/api/v1/coordination/consent',
    fetchOpts,
  );

  const stats = statsData?.data;
  const health = healthData?.data;
  const workspaces = wsData?.data?.workspaces ?? [];
  const executions = execData?.data?.executions ?? [];
  const consents = consentData?.data?.consents ?? [];

  const isLoading = statsLoading || wsLoading;

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <div className="flex items-center gap-3">
              <Link
                href="/self-improve"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [SELF-IMPROVE]
              </Link>
              <Link
                href="/autonomous"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [AUTONOMOUS]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <div className="container mx-auto px-4 py-6">
          <div className="mb-6 flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
                {'>'} MULTI-AGENT COORDINATION
              </h1>
              <p className="text-text-muted font-theme-data text-sm">
                Federated cross-workspace execution, worktree lifecycle, task dispatch, and consent
                management.
              </p>
            </div>
            {health && (
              <div
                className={`px-3 py-1 rounded border text-xs font-theme-data ${
                  health.healthy
                    ? 'border-[var(--accent)]/50 text-[var(--accent)] bg-[var(--accent)]/10'
                    : 'border-red-400/50 text-red-400 bg-red-400/10'
                }`}
              >
                {health.healthy ? 'HEALTHY' : 'DEGRADED'}
              </div>
            )}
          </div>

          <PanelErrorBoundary panelName="Coordination">
            {isLoading ? (
              <div className="text-[var(--accent)] font-theme-data animate-pulse text-center py-12">
                Loading coordination data...
              </div>
            ) : !stats ? (
              <div className="p-8 bg-surface border border-border rounded-lg text-center">
                <p className="text-text-muted font-theme-data">
                  Coordination module not available. The{' '}
                  <code className="text-[var(--accent)]">aragora.coordination</code> package
                  provides cross-workspace federation, worktree management, and task dispatch.
                </p>
              </div>
            ) : (
              <div className="space-y-6">
                {/* Stats row */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="p-4 bg-surface border border-border rounded-lg text-center">
                    <div className="text-3xl font-theme-data font-bold text-[var(--accent)]">
                      {stats.total_workspaces}
                    </div>
                    <div className="text-xs text-text-muted uppercase">Workspaces</div>
                  </div>
                  <div className="p-4 bg-surface border border-border rounded-lg text-center">
                    <div className="text-3xl font-theme-data font-bold text-blue-400">
                      {stats.active_executions}
                    </div>
                    <div className="text-xs text-text-muted uppercase">Active Executions</div>
                  </div>
                  <div className="p-4 bg-surface border border-border rounded-lg text-center">
                    <div className="text-3xl font-theme-data font-bold text-purple-400">
                      {stats.total_consents}
                    </div>
                    <div className="text-xs text-text-muted uppercase">Active Consents</div>
                  </div>
                  <div className="p-4 bg-surface border border-border rounded-lg text-center">
                    <div className="text-3xl font-theme-data font-bold text-gold">
                      {stats.federation_policies}
                    </div>
                    <div className="text-xs text-text-muted uppercase">Federation Policies</div>
                  </div>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {/* Workspaces */}
                  <div className="p-4 bg-surface border border-border rounded-lg">
                    <h2 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
                      Registered Workspaces
                    </h2>
                    {workspaces.length > 0 ? (
                      <div className="space-y-2 max-h-[350px] overflow-y-auto">
                        {workspaces.map((ws) => (
                          <div
                            key={ws.workspace_id}
                            className="p-3 bg-bg rounded flex items-center justify-between"
                          >
                            <div>
                              <div className="text-sm text-text font-theme-data">{ws.name}</div>
                              <div className="text-xs text-text-muted">
                                {ws.workspace_id.substring(0, 12)}...
                              </div>
                            </div>
                            <span className={`text-xs font-theme-data ${statusColor(ws.status)}`}>
                              {ws.status.toUpperCase()}
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-text-muted text-sm">No workspaces registered.</p>
                    )}
                  </div>

                  {/* Executions */}
                  <div className="p-4 bg-surface border border-border rounded-lg">
                    <h2 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
                      Recent Executions
                    </h2>
                    {executions.length > 0 ? (
                      <div className="space-y-2 max-h-[350px] overflow-y-auto">
                        {executions.map((exec) => (
                          <div key={exec.execution_id} className="p-3 bg-bg rounded">
                            <div className="flex items-center justify-between mb-1">
                              <span className="text-xs font-theme-data text-text-muted">
                                {exec.execution_id.substring(0, 12)}...
                              </span>
                              <span
                                className={`text-xs font-theme-data ${statusColor(exec.status)}`}
                              >
                                {exec.status.toUpperCase()}
                              </span>
                            </div>
                            <div className="text-sm text-text">{exec.operation}</div>
                            <div className="text-xs text-text-muted mt-1">
                              {exec.source_workspace.substring(0, 8)} {'→'}{' '}
                              {exec.target_workspace.substring(0, 8)}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-text-muted text-sm">No recent executions.</p>
                    )}
                  </div>
                </div>

                {/* Consents */}
                <div className="p-4 bg-surface border border-border rounded-lg">
                  <h2 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
                    Data Sharing Consents
                  </h2>
                  {consents.length > 0 ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                      {consents.map((consent) => (
                        <div
                          key={consent.consent_id}
                          className="p-3 bg-bg rounded flex items-center justify-between"
                        >
                          <div>
                            <div className="text-xs font-theme-data text-text-muted">
                              {consent.workspace_id.substring(0, 12)}...
                            </div>
                            <span className="px-1.5 py-0.5 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] rounded">
                              {consent.scope}
                            </span>
                          </div>
                          {consent.expires_at && (
                            <span className="text-xs text-text-muted">
                              exp {new Date(consent.expires_at).toLocaleDateString()}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-text-muted text-sm">No active data sharing consents.</p>
                  )}
                </div>
              </div>
            )}
          </PanelErrorBoundary>
        </div>

        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // MULTI-AGENT COORDINATION</p>
        </footer>
      </main>
    </>
  );
}
