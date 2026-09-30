'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';
import { getRuntimeBackendConfig } from '@/components/BackendSelector';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useSWRFetch } from '@/hooks/useSWRFetch';

// ---------------------------------------------------------------------------
// Types matching backup_handler.py and dr_handler.py response shapes
// ---------------------------------------------------------------------------

interface BackupEntry {
  id: string;
  source_path: string;
  backup_path: string;
  backup_type: string;
  status: string;
  created_at: string;
  compressed_size_bytes: number;
  verified: boolean;
  checksum: string | null;
  metadata: Record<string, unknown>;
}

interface BackupsResponse {
  backups: BackupEntry[];
  pagination: { limit: number; offset: number; total: number; has_more: boolean };
}

interface BackupStats {
  stats: {
    total_backups: number;
    verified_backups: number;
    failed_backups: number;
    total_size_bytes: number;
    total_size_mb: number;
    latest_backup: BackupEntry | null;
    retention_policy: {
      keep_daily: number;
      keep_weekly: number;
      keep_monthly: number;
      min_backups: number;
    };
  };
  generated_at: string;
}

interface DRStatus {
  status: string;
  readiness_score: number;
  backup_status: {
    total_backups: number;
    verified_backups: number;
    failed_backups: number;
    latest_backup: BackupEntry | null;
    hours_since_backup: number | null;
  };
  rpo_status: { target_hours: number; compliant: boolean; current_hours: number | null };
  issues: string[];
  recommendations: string[];
  checked_at: string;
}

interface DRObjectives {
  rpo: {
    target_hours: number;
    current_hours: number | null;
    compliant: boolean;
    violations_last_7_days: number;
  };
  rto: { target_minutes: number; estimated_minutes: number | null; compliant: boolean };
  backup_coverage: {
    total_backups: number;
    backups_last_7_days: number;
    latest_backup: BackupEntry | null;
  };
  generated_at: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    completed: 'text-[var(--acid-green)] bg-[var(--acid-green)]/10 border-[var(--acid-green)]/30',
    verified: 'text-[var(--acid-cyan)] bg-[var(--acid-cyan)]/10 border-[var(--acid-cyan)]/30',
    failed: 'text-red-400 bg-red-500/10 border-red-500/30',
    pending: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
    in_progress: 'text-blue-400 bg-blue-500/10 border-blue-500/30',
    expired: 'text-[var(--text-muted)] bg-[var(--surface)] border-[var(--border)]',
  };

  const style = colors[status.toLowerCase()] || colors.pending;

  return (
    <span className={`px-2 py-0.5 text-[10px] font-theme-data uppercase rounded border ${style}`}>
      {status}
    </span>
  );
}

function ReadinessGauge({ score }: { score: number }) {
  const color = score >= 90 ? 'var(--acid-green)' : score >= 70 ? '#facc15' : '#f87171';
  const status = score >= 90 ? 'HEALTHY' : score >= 70 ? 'WARNING' : 'CRITICAL';

  return (
    <div className="flex flex-col items-center">
      <svg width={120} height={120} viewBox="0 0 120 120">
        {/* Background circle */}
        <circle cx={60} cy={60} r={50} fill="none" stroke="var(--border)" strokeWidth={8} />
        {/* Progress arc */}
        <circle
          cx={60}
          cy={60}
          r={50}
          fill="none"
          stroke={color}
          strokeWidth={8}
          strokeLinecap="round"
          strokeDasharray={`${(score / 100) * 314} 314`}
          transform="rotate(-90 60 60)"
          style={{ transition: 'stroke-dasharray 0.5s ease' }}
        />
        {/* Score text */}
        <text
          x={60}
          y={55}
          textAnchor="middle"
          className="font-theme-data text-2xl"
          fill={color}
          fontSize={28}
        >
          {score}
        </text>
        <text
          x={60}
          y={75}
          textAnchor="middle"
          className="font-theme-data text-xs"
          fill="var(--text-muted)"
          fontSize={10}
        >
          {status}
        </text>
      </svg>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

function formatTimestamp(ts: string | null): string {
  if (!ts) return '--';
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

// ---------------------------------------------------------------------------
// Page Component
// ---------------------------------------------------------------------------

type ActiveTab = 'overview' | 'backups' | 'dr';

export default function BackupDRPage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('overview');
  const [offset, setOffset] = useState(0);
  const [creatingBackup, setCreatingBackup] = useState(false);
  const [runningDrill, setRunningDrill] = useState(false);
  const [drillResult, setDrillResult] = useState<Record<string, unknown> | null>(null);

  const PAGE_SIZE = 20;
  const apiBase = getRuntimeBackendConfig().config.api;

  // Fetch backup stats
  const { data: statsData, isLoading: statsLoading } = useSWRFetch<BackupStats>(
    '/api/v2/backups/stats',
    { refreshInterval: 30000 },
  );

  // Fetch DR status
  const { data: drStatus, isLoading: drLoading } = useSWRFetch<DRStatus>('/api/v2/dr/status', {
    refreshInterval: 30000,
  });

  // Fetch DR objectives
  const { data: drObjectives } = useSWRFetch<DRObjectives>(
    activeTab === 'dr' ? '/api/v2/dr/objectives' : null,
    { refreshInterval: 60000 },
  );

  // Fetch backup list
  const {
    data: backupsData,
    isLoading: backupsLoading,
    mutate: refreshBackups,
  } = useSWRFetch<BackupsResponse>(
    activeTab === 'backups' ? `/api/v2/backups?limit=${PAGE_SIZE}&offset=${offset}` : null,
    { refreshInterval: 30000 },
  );

  const stats = statsData?.stats;
  const backups = backupsData?.backups ?? [];
  const backupsTotal = backupsData?.pagination?.total ?? 0;

  // Create backup
  const handleCreateBackup = useCallback(async () => {
    setCreatingBackup(true);
    try {
      const response = await fetch(`${apiBase}/api/v2/backups`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backup_type: 'full' }),
      });
      if (response.ok) {
        refreshBackups();
      }
    } catch {
      // creation failed silently
    } finally {
      setCreatingBackup(false);
    }
  }, [apiBase, refreshBackups]);

  // Run DR drill
  const handleRunDrill = useCallback(
    async (drillType: string) => {
      setRunningDrill(true);
      setDrillResult(null);
      try {
        const response = await fetch(`${apiBase}/api/v2/dr/drill`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ drill_type: drillType }),
        });
        if (response.ok) {
          const data = await response.json();
          setDrillResult(data);
        }
      } catch {
        // drill failed silently
      } finally {
        setRunningDrill(false);
      }
    },
    [apiBase],
  );

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Header */}
          <div className="mb-6">
            <div className="flex items-center gap-2 mb-2">
              <Link
                href="/admin"
                className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
              >
                Admin
              </Link>
              <span className="text-[var(--text-muted)]">/</span>
              <span className="text-xs font-theme-data text-[var(--acid-green)]">Backup & DR</span>
            </div>
            <h1 className="text-xl font-theme-data text-[var(--acid-green)]">
              {'>'} BACKUP & DISASTER RECOVERY
            </h1>
            <p className="text-xs text-[var(--text-muted)] font-theme-data mt-1">
              Manage backups, verify integrity, run DR drills, and monitor RPO/RTO compliance.
            </p>
          </div>

          {/* Tabs */}
          <div className="flex gap-2 mb-6">
            {[
              { key: 'overview' as const, label: 'OVERVIEW' },
              { key: 'backups' as const, label: 'BACKUPS' },
              { key: 'dr' as const, label: 'DISASTER RECOVERY' },
            ].map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                  activeTab === key
                    ? 'border-[var(--acid-green)] bg-[var(--acid-green)]/10 text-[var(--acid-green)]'
                    : 'border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)]'
                }`}
              >
                [{label}]
              </button>
            ))}
          </div>

          <PanelErrorBoundary panelName="Backup & DR">
            {/* Overview Tab */}
            {activeTab === 'overview' && (
              <div>
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                  {/* Readiness Gauge */}
                  <div className="p-6 bg-[var(--surface)] border border-[var(--border)] flex flex-col items-center">
                    <h2 className="text-sm font-theme-data text-[var(--acid-green)] uppercase mb-4">
                      DR Readiness
                    </h2>
                    {drLoading ? (
                      <div className="h-32 flex items-center justify-center text-[var(--text-muted)] font-theme-data animate-pulse">
                        Loading...
                      </div>
                    ) : drStatus ? (
                      <ReadinessGauge score={drStatus.readiness_score} />
                    ) : (
                      <p className="text-xs font-theme-data text-[var(--text-muted)]">
                        Unavailable
                      </p>
                    )}
                  </div>

                  {/* Stats Cards */}
                  <div className="lg:col-span-2 grid grid-cols-2 md:grid-cols-3 gap-4">
                    <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                      <div className="text-2xl font-theme-data text-[var(--acid-green)]">
                        {statsLoading ? '-' : (stats?.total_backups ?? 0)}
                      </div>
                      <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                        Total Backups
                      </div>
                    </div>
                    <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                      <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                        {statsLoading ? '-' : (stats?.verified_backups ?? 0)}
                      </div>
                      <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                        Verified
                      </div>
                    </div>
                    <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                      <div
                        className={`text-2xl font-theme-data ${(stats?.failed_backups ?? 0) > 0 ? 'text-red-400' : 'text-[var(--acid-green)]'}`}
                      >
                        {statsLoading ? '-' : (stats?.failed_backups ?? 0)}
                      </div>
                      <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                        Failed
                      </div>
                    </div>
                    <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                      <div className="text-2xl font-theme-data text-purple-400">
                        {statsLoading ? '-' : stats ? formatBytes(stats.total_size_bytes) : '0 B'}
                      </div>
                      <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                        Total Size
                      </div>
                    </div>
                    <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                      <div
                        className={`text-2xl font-theme-data ${drStatus?.rpo_status?.compliant ? 'text-[var(--acid-green)]' : 'text-red-400'}`}
                      >
                        {drStatus?.rpo_status?.current_hours != null
                          ? `${drStatus.rpo_status.current_hours}h`
                          : '--'}
                      </div>
                      <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                        RPO ({drStatus?.rpo_status?.target_hours ?? 24}h target)
                      </div>
                    </div>
                    <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                      <div className="text-2xl font-theme-data text-yellow-400">
                        {stats?.retention_policy
                          ? `${stats.retention_policy.keep_daily}d/${stats.retention_policy.keep_weekly}w/${stats.retention_policy.keep_monthly}m`
                          : '--'}
                      </div>
                      <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                        Retention
                      </div>
                    </div>
                  </div>
                </div>

                {/* Issues & Recommendations */}
                {drStatus &&
                  (drStatus.issues.length > 0 || drStatus.recommendations.length > 0) && (
                    <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-6">
                      {drStatus.issues.length > 0 && (
                        <div className="p-4 bg-red-500/5 border border-red-500/30">
                          <h3 className="text-sm font-theme-data text-red-400 uppercase mb-3">
                            Issues
                          </h3>
                          <ul className="space-y-2">
                            {drStatus.issues.map((issue, i) => (
                              <li
                                key={i}
                                className="text-xs font-theme-data text-red-400 flex items-start gap-2"
                              >
                                <span className="text-red-500 shrink-0">!</span>
                                {issue}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {drStatus.recommendations.length > 0 && (
                        <div className="p-4 bg-[var(--acid-cyan)]/5 border border-[var(--acid-cyan)]/30">
                          <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] uppercase mb-3">
                            Recommendations
                          </h3>
                          <ul className="space-y-2">
                            {drStatus.recommendations.map((rec, i) => (
                              <li
                                key={i}
                                className="text-xs font-theme-data text-[var(--acid-cyan)] flex items-start gap-2"
                              >
                                <span className="shrink-0">-</span>
                                {rec}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
              </div>
            )}

            {/* Backups Tab */}
            {activeTab === 'backups' && (
              <div>
                <div className="flex items-center gap-3 mb-4">
                  <button
                    onClick={handleCreateBackup}
                    disabled={creatingBackup}
                    className="px-4 py-2 text-xs font-theme-data text-[var(--acid-green)] border border-[var(--acid-green)]/30 bg-[var(--acid-green)]/10 hover:bg-[var(--acid-green)]/20 transition-colors disabled:opacity-50"
                  >
                    {creatingBackup ? 'CREATING...' : '+ CREATE BACKUP'}
                  </button>
                  <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                    {backupsTotal} backup{backupsTotal !== 1 ? 's' : ''}
                  </span>
                </div>

                <div className="bg-[var(--surface)] border border-[var(--border)] overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-[10px] font-theme-data text-[var(--text-muted)] uppercase border-b border-[var(--border)]">
                          <th className="px-4 py-3">ID</th>
                          <th className="px-4 py-3">Created</th>
                          <th className="px-4 py-3">Type</th>
                          <th className="px-4 py-3">Status</th>
                          <th className="px-4 py-3">Size</th>
                          <th className="px-4 py-3">Verified</th>
                          <th className="px-4 py-3">Checksum</th>
                        </tr>
                      </thead>
                      <tbody>
                        {backupsLoading ? (
                          <tr>
                            <td
                              colSpan={7}
                              className="px-4 py-12 text-center text-[var(--text-muted)] font-theme-data animate-pulse"
                            >
                              Loading backups...
                            </td>
                          </tr>
                        ) : backups.length === 0 ? (
                          <tr>
                            <td
                              colSpan={7}
                              className="px-4 py-12 text-center text-[var(--text-muted)] font-theme-data"
                            >
                              No backups found. Create one to get started.
                            </td>
                          </tr>
                        ) : (
                          backups.map((backup) => (
                            <tr
                              key={backup.id}
                              className="border-b border-[var(--border)]/50 hover:bg-[var(--acid-green)]/5 transition-colors"
                            >
                              <td className="px-4 py-3">
                                <span className="font-theme-data text-xs text-[var(--acid-cyan)]">
                                  {backup.id.substring(0, 16)}
                                </span>
                              </td>
                              <td className="px-4 py-3 text-xs font-theme-data text-[var(--text-muted)]">
                                {formatTimestamp(backup.created_at)}
                              </td>
                              <td className="px-4 py-3">
                                <span className="text-xs font-theme-data text-purple-400 uppercase">
                                  {backup.backup_type}
                                </span>
                              </td>
                              <td className="px-4 py-3">
                                <StatusBadge status={backup.status} />
                              </td>
                              <td className="px-4 py-3 text-xs font-theme-data text-[var(--text)]">
                                {formatBytes(backup.compressed_size_bytes)}
                              </td>
                              <td className="px-4 py-3">
                                <span
                                  className={`text-xs font-theme-data ${backup.verified ? 'text-[var(--acid-green)]' : 'text-[var(--text-muted)]'}`}
                                >
                                  {backup.verified ? 'YES' : 'NO'}
                                </span>
                              </td>
                              <td className="px-4 py-3">
                                {backup.checksum ? (
                                  <span
                                    className="text-[10px] font-theme-data text-purple-400"
                                    title={backup.checksum}
                                  >
                                    {backup.checksum.substring(0, 12)}...
                                  </span>
                                ) : (
                                  <span className="text-[var(--text-muted)] text-xs font-theme-data">
                                    --
                                  </span>
                                )}
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Pagination */}
                {backupsTotal > PAGE_SIZE && (
                  <div className="flex items-center justify-between mt-4">
                    <button
                      onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                      disabled={offset === 0}
                      className="px-3 py-1.5 text-xs font-theme-data text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 disabled:opacity-30 transition-colors"
                    >
                      PREV
                    </button>
                    <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                      {offset + 1}-{Math.min(offset + PAGE_SIZE, backupsTotal)} of {backupsTotal}
                    </span>
                    <button
                      onClick={() => setOffset(offset + PAGE_SIZE)}
                      disabled={offset + PAGE_SIZE >= backupsTotal}
                      className="px-3 py-1.5 text-xs font-theme-data text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 disabled:opacity-30 transition-colors"
                    >
                      NEXT
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* DR Tab */}
            {activeTab === 'dr' && (
              <div className="space-y-6">
                {/* RPO / RTO Cards */}
                {drObjectives && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* RPO */}
                    <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
                      <h3 className="text-sm font-theme-data text-[var(--acid-green)] uppercase mb-4">
                        Recovery Point Objective (RPO)
                      </h3>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                            Target
                          </div>
                          <div className="text-xl font-theme-data text-[var(--text)]">
                            {drObjectives.rpo.target_hours}h
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                            Current
                          </div>
                          <div
                            className={`text-xl font-theme-data ${drObjectives.rpo.compliant ? 'text-[var(--acid-green)]' : 'text-red-400'}`}
                          >
                            {drObjectives.rpo.current_hours != null
                              ? `${drObjectives.rpo.current_hours}h`
                              : '--'}
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                            Status
                          </div>
                          <div
                            className={`text-sm font-theme-data ${drObjectives.rpo.compliant ? 'text-[var(--acid-green)]' : 'text-red-400'}`}
                          >
                            {drObjectives.rpo.compliant ? 'COMPLIANT' : 'VIOLATION'}
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                            Violations (7d)
                          </div>
                          <div
                            className={`text-sm font-theme-data ${drObjectives.rpo.violations_last_7_days > 0 ? 'text-red-400' : 'text-[var(--acid-green)]'}`}
                          >
                            {drObjectives.rpo.violations_last_7_days}
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* RTO */}
                    <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
                      <h3 className="text-sm font-theme-data text-[var(--acid-green)] uppercase mb-4">
                        Recovery Time Objective (RTO)
                      </h3>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                            Target
                          </div>
                          <div className="text-xl font-theme-data text-[var(--text)]">
                            {drObjectives.rto.target_minutes}m
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                            Estimated
                          </div>
                          <div
                            className={`text-xl font-theme-data ${drObjectives.rto.compliant ? 'text-[var(--acid-green)]' : 'text-red-400'}`}
                          >
                            {drObjectives.rto.estimated_minutes != null
                              ? `${drObjectives.rto.estimated_minutes}m`
                              : '--'}
                          </div>
                        </div>
                        <div className="col-span-2">
                          <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                            Status
                          </div>
                          <div
                            className={`text-sm font-theme-data ${drObjectives.rto.compliant ? 'text-[var(--acid-green)]' : 'text-red-400'}`}
                          >
                            {drObjectives.rto.compliant ? 'WITHIN TARGET' : 'EXCEEDS TARGET'}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* DR Drills */}
                <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
                  <h3 className="text-sm font-theme-data text-[var(--acid-green)] uppercase mb-4">
                    DR Drills
                  </h3>
                  <p className="text-xs font-theme-data text-[var(--text-muted)] mb-4">
                    Run simulated recovery operations to validate DR readiness. These are dry-run
                    operations and will not affect production data.
                  </p>
                  <div className="flex flex-wrap gap-3">
                    <button
                      onClick={() => handleRunDrill('restore_test')}
                      disabled={runningDrill}
                      className="px-4 py-2 text-xs font-theme-data text-[var(--acid-green)] border border-[var(--acid-green)]/30 bg-[var(--acid-green)]/10 hover:bg-[var(--acid-green)]/20 transition-colors disabled:opacity-50"
                    >
                      {runningDrill ? 'RUNNING...' : 'RESTORE TEST'}
                    </button>
                    <button
                      onClick={() => handleRunDrill('full_recovery_sim')}
                      disabled={runningDrill}
                      className="px-4 py-2 text-xs font-theme-data text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/10 hover:bg-[var(--acid-cyan)]/20 transition-colors disabled:opacity-50"
                    >
                      {runningDrill ? 'RUNNING...' : 'FULL RECOVERY SIM'}
                    </button>
                    <button
                      onClick={() => handleRunDrill('failover_test')}
                      disabled={runningDrill}
                      className="px-4 py-2 text-xs font-theme-data text-purple-400 border border-purple-400/30 bg-purple-400/10 hover:bg-purple-400/20 transition-colors disabled:opacity-50"
                    >
                      {runningDrill ? 'RUNNING...' : 'FAILOVER TEST'}
                    </button>
                  </div>
                </div>

                {/* Drill Result */}
                {drillResult && (
                  <div
                    className={`p-4 border font-theme-data text-sm ${
                      (drillResult as { success?: boolean }).success
                        ? 'bg-[var(--acid-green)]/5 border-[var(--acid-green)]/30'
                        : 'bg-red-500/5 border-red-500/30'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <h4
                        className={`text-sm font-theme-data uppercase ${
                          (drillResult as { success?: boolean }).success
                            ? 'text-[var(--acid-green)]'
                            : 'text-red-400'
                        }`}
                      >
                        Drill Result:{' '}
                        {(drillResult as { success?: boolean }).success ? 'PASSED' : 'FAILED'}
                      </h4>
                      <span className="text-xs text-[var(--text-muted)]">
                        {(drillResult as { duration_seconds?: number }).duration_seconds != null
                          ? `${(drillResult as { duration_seconds: number }).duration_seconds.toFixed(2)}s`
                          : ''}
                      </span>
                    </div>
                    {Array.isArray((drillResult as { steps?: unknown[] }).steps) && (
                      <div className="space-y-1">
                        {(
                          drillResult as { steps: Array<{ step: string; status: string }> }
                        ).steps.map((step, i) => (
                          <div key={i} className="flex items-center gap-2 text-xs">
                            <span
                              className={
                                step.status === 'completed'
                                  ? 'text-[var(--acid-green)]'
                                  : step.status === 'failed'
                                    ? 'text-red-400'
                                    : 'text-yellow-400'
                              }
                            >
                              [{step.status.toUpperCase()}]
                            </span>
                            <span className="text-[var(--text-muted)]">{step.step}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    <button
                      onClick={() => setDrillResult(null)}
                      className="mt-3 text-xs text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
                    >
                      [DISMISS]
                    </button>
                  </div>
                )}
              </div>
            )}
          </PanelErrorBoundary>

          {/* Quick Links */}
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              href="/admin"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Admin Panel
            </Link>
            <Link
              href="/audit-trail"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Audit Trail
            </Link>
            <Link
              href="/system-status"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              System Status
            </Link>
          </div>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--acid-green)]/20 mt-8">
          <div className="text-[var(--acid-green)]/50 mb-2" aria-hidden="true">
            {'='.repeat(40)}
          </div>
          <p className="text-[var(--text-muted)]">{'>'} ARAGORA // BACKUP & DISASTER RECOVERY</p>
        </footer>
      </main>
    </>
  );
}
