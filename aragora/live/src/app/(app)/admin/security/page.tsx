'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';
import { buildSecretsScanUrl } from './secretsScan';

interface SecurityStatus {
  encryption_enabled: boolean;
  active_key_id: string;
  key_version: number;
  key_created_at: string;
  key_rotation_due: boolean;
  last_rotation_at?: string;
  algorithm: string;
}

interface SecretFinding {
  id: string;
  secret_type: string;
  file_path: string;
  line_number: number;
  matched_text: string;
  context_line: string;
  severity: string;
  confidence: number;
  is_in_history: boolean;
}

interface SecretsScanResult {
  scan_id: string;
  repository: string;
  status: string;
  files_scanned: number;
  scanned_history: boolean;
  secrets: SecretFinding[];
  summary: {
    total_secrets: number;
    critical_count: number;
    high_count: number;
    medium_count: number;
    low_count: number;
  };
}

interface SecurityHealth {
  status: 'healthy' | 'degraded' | 'unhealthy';
  encryption_service: { available: boolean; latency_ms?: number };
  key_age_days: number;
  rotation_recommended: boolean;
  compliance: { soc2_compliant: boolean; key_rotation_policy: string; last_audit?: string };
}

interface EncryptionKey {
  key_id: string;
  version: number;
  algorithm: string;
  created_at: string;
  expires_at?: string;
  status: 'active' | 'rotating' | 'retired' | 'compromised';
  used_for: string[];
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    healthy: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40',
    degraded: 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40',
    unhealthy: 'bg-acid-red/20 text-acid-red border-acid-red/40',
    active: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40',
    rotating: 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40',
    retired: 'bg-text-muted/20 text-text-muted border-text-muted/40',
    compromised: 'bg-acid-red/20 text-acid-red border-acid-red/40',
  };

  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data rounded border ${colors[status] || colors.degraded}`}
    >
      {status.toUpperCase()}
    </span>
  );
}

function formatDate(isoString?: string): string {
  if (!isoString) return 'N/A';
  return new Date(isoString).toLocaleDateString();
}

function formatDateTime(isoString?: string): string {
  if (!isoString) return 'N/A';
  return new Date(isoString).toLocaleString();
}

function calculateKeyAge(createdAt: string): number {
  const created = new Date(createdAt);
  const now = new Date();
  return Math.floor((now.getTime() - created.getTime()) / (1000 * 60 * 60 * 24));
}

export default function SecurityAdminPage() {
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();
  const token = tokens?.access_token;

  const [status, setStatus] = useState<SecurityStatus | null>(null);
  const [health, setHealth] = useState<SecurityHealth | null>(null);
  const [keys, setKeys] = useState<EncryptionKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [rotationConfirm, setRotationConfirm] = useState(false);

  // Secrets scanning state
  const [secretsScan, setSecretsScan] = useState<SecretsScanResult | null>(null);
  const [secretsLoading, setSecretsLoading] = useState(false);
  const [repoPath, setRepoPath] = useState('');
  const [includeHistory, setIncludeHistory] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};

      // Fetch security status
      const statusRes = await fetch(`${backendConfig.api}/api/v1/admin/security/status`, {
        headers,
      });
      if (statusRes.ok) {
        const data = await statusRes.json();
        setStatus(data);
      }

      // Fetch security health
      const healthRes = await fetch(`${backendConfig.api}/api/v1/admin/security/health`, {
        headers,
      });
      if (healthRes.ok) {
        const data = await healthRes.json();
        setHealth(data);
      }

      // Fetch encryption keys
      const keysRes = await fetch(`${backendConfig.api}/api/v1/admin/security/keys`, { headers });
      if (keysRes.ok) {
        const data = await keysRes.json();
        setKeys(data.keys || []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch security data');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, token]);

  useEffect(() => {
    fetchData();
    // Refresh every 30 seconds
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleSecretsScan = async () => {
    if (!repoPath.trim()) {
      setError('Please enter a repository path');
      return;
    }

    setSecretsLoading(true);
    setError(null);
    setSecretsScan(null);

    try {
      const headers: HeadersInit = {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      };

      // Start the scan
      const res = await fetch(buildSecretsScanUrl(backendConfig.api), {
        method: 'POST',
        headers,
        body: JSON.stringify({
          repo_path: repoPath,
          include_history: includeHistory,
          history_depth: 100,
        }),
      });

      if (!res.ok) {
        throw new Error('Failed to start secrets scan');
      }

      const scanData = await res.json();

      // Poll for results
      if (scanData.scan_id) {
        let attempts = 0;
        const maxAttempts = 60; // 5 minutes max

        const pollResults = async () => {
          try {
            const resultRes = await fetch(
              buildSecretsScanUrl(backendConfig.api, scanData.scan_id),
              { headers },
            );

            if (!resultRes.ok) {
              throw new Error('Failed to fetch secrets scan status');
            }

            const result = await resultRes.json();
            if (result.scan_result?.status === 'completed') {
              setSecretsScan(result.scan_result);
              setSecretsLoading(false);
              return;
            }

            if (result.scan_result?.status === 'failed') {
              throw new Error(result.scan_result.error || 'Scan failed');
            }

            attempts++;
            if (attempts < maxAttempts) {
              setTimeout(pollResults, 5000);
              return;
            }

            throw new Error('Scan timed out');
          } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to scan for secrets');
            setSecretsLoading(false);
          }
        };

        setTimeout(pollResults, 2000);
        return;
      }

      setError('Secrets scan did not return a scan ID');
      setSecretsLoading(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to scan for secrets');
      setSecretsLoading(false);
    }
  };

  const handleRotateKey = async () => {
    if (!rotationConfirm) {
      setRotationConfirm(true);
      return;
    }

    setActionLoading('rotate');
    try {
      const headers: HeadersInit = {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      };
      const res = await fetch(`${backendConfig.api}/api/v1/admin/security/rotate-key`, {
        method: 'POST',
        headers,
      });
      if (res.ok) {
        setRotationConfirm(false);
        fetchData();
      } else {
        const data = await res.json();
        setError(data.error || 'Failed to rotate key');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to rotate key');
    } finally {
      setActionLoading(null);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-[var(--accent)] font-theme-data animate-pulse">
          Loading Security Dashboard...
        </div>
      </div>
    );
  }

  const keyAgeDays = status?.key_created_at ? calculateKeyAge(status.key_created_at) : 0;
  const rotationDue = keyAgeDays > 90; // SOC 2 recommends 90-day rotation

  return (
    <div className="min-h-screen bg-background relative">
      <Scanlines />
      <CRTVignette />

      <div className="relative z-10 p-4 md:p-6 space-y-6 max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <Link
              href="/admin"
              className="text-text-muted hover:text-text mb-2 inline-block text-sm"
            >
              &larr; Back to Admin
            </Link>
            <h1 className="text-2xl font-theme-data text-[var(--accent)]">Security Dashboard</h1>
            <p className="text-sm text-text-muted font-theme-data">
              Encryption keys and security compliance
            </p>
          </div>
          <div className="flex items-center gap-4">
            <BackendSelector />
            <ThemeToggle />
          </div>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="card p-4 border-acid-red/40 bg-acid-red/10">
            <div className="flex items-center justify-between">
              <span className="text-acid-red font-theme-data text-sm">{error}</span>
              <button onClick={() => setError(null)} className="text-text-muted hover:text-text">
                &times;
              </button>
            </div>
          </div>
        )}

        {/* Security Status Overview */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="card p-4">
            <div className="text-xs font-theme-data text-text-muted mb-1">Encryption</div>
            <div
              className={`text-xl font-theme-data ${status?.encryption_enabled ? 'text-[var(--accent)]' : 'text-acid-red'}`}
            >
              {status?.encryption_enabled ? 'ENABLED' : 'DISABLED'}
            </div>
          </div>
          <div className="card p-4">
            <div className="text-xs font-theme-data text-text-muted mb-1">Algorithm</div>
            <div className="text-xl font-theme-data text-[var(--acid-cyan)]">
              {status?.algorithm || 'AES-256-GCM'}
            </div>
          </div>
          <div className="card p-4">
            <div className="text-xs font-theme-data text-text-muted mb-1">Key Age</div>
            <div
              className={`text-xl font-theme-data ${rotationDue ? 'text-[var(--acid-yellow)]' : 'text-[var(--accent)]'}`}
            >
              {keyAgeDays} days
            </div>
          </div>
          <div className="card p-4">
            <div className="text-xs font-theme-data text-text-muted mb-1">SOC 2 Status</div>
            <div
              className={`text-xl font-theme-data ${health?.compliance?.soc2_compliant ? 'text-[var(--accent)]' : 'text-[var(--acid-yellow)]'}`}
            >
              {health?.compliance?.soc2_compliant ? 'COMPLIANT' : 'REVIEW'}
            </div>
          </div>
        </div>

        {/* Key Rotation Warning */}
        {rotationDue && (
          <div className="card p-4 border-acid-yellow/40 bg-acid-yellow/10">
            <div className="flex items-center gap-3">
              <span className="text-[var(--acid-yellow)] text-2xl">!</span>
              <div>
                <div className="text-[var(--acid-yellow)] font-theme-data">
                  Key Rotation Recommended
                </div>
                <div className="text-sm text-text-muted font-theme-data">
                  Current key is {keyAgeDays} days old. SOC 2 CC6.1 recommends rotation every 90
                  days.
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Active Key Details */}
        <div className="card p-4">
          <h2 className="text-lg font-theme-data text-text mb-4">Active Encryption Key</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
            <div>
              <div className="text-xs font-theme-data text-text-muted">Key ID</div>
              <div
                className="text-sm font-theme-data text-text truncate"
                title={status?.active_key_id}
              >
                {status?.active_key_id?.slice(0, 16)}...
              </div>
            </div>
            <div>
              <div className="text-xs font-theme-data text-text-muted">Version</div>
              <div className="text-sm font-theme-data text-text">v{status?.key_version || 1}</div>
            </div>
            <div>
              <div className="text-xs font-theme-data text-text-muted">Created</div>
              <div className="text-sm font-theme-data text-text">
                {formatDateTime(status?.key_created_at)}
              </div>
            </div>
            <div>
              <div className="text-xs font-theme-data text-text-muted">Last Rotation</div>
              <div className="text-sm font-theme-data text-text">
                {formatDateTime(status?.last_rotation_at)}
              </div>
            </div>
          </div>

          {/* Key Rotation Action */}
          <div className="border-t border-border pt-4 mt-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-theme-data text-text">Rotate Encryption Key</div>
                <div className="text-xs font-theme-data text-text-muted">
                  Creates a new key and re-encrypts all secrets. Existing data will be decrypted
                  with old key and re-encrypted with new key.
                </div>
              </div>
              <div className="flex items-center gap-2">
                {rotationConfirm && (
                  <button
                    onClick={() => setRotationConfirm(false)}
                    className="px-4 py-2 font-theme-data text-sm rounded border border-border text-text-muted hover:text-text"
                  >
                    Cancel
                  </button>
                )}
                <button
                  onClick={handleRotateKey}
                  disabled={actionLoading !== null}
                  className={`px-4 py-2 font-theme-data text-sm rounded border ${
                    rotationConfirm
                      ? 'border-acid-red/40 bg-acid-red/10 text-acid-red hover:bg-acid-red/20'
                      : 'border-acid-yellow/40 bg-acid-yellow/10 text-[var(--acid-yellow)] hover:bg-acid-yellow/20'
                  } disabled:opacity-50 disabled:cursor-not-allowed`}
                >
                  {actionLoading === 'rotate'
                    ? 'Rotating...'
                    : rotationConfirm
                      ? 'Confirm Rotation'
                      : 'Rotate Key'}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Encryption Keys History */}
        <div className="card p-4">
          <h2 className="text-lg font-theme-data text-text mb-4">Key History</h2>
          {keys.length === 0 ? (
            <div className="text-sm font-theme-data text-text-muted">No key history available</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm font-theme-data">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left py-2 text-text-muted font-normal">Key ID</th>
                    <th className="text-left py-2 text-text-muted font-normal">Version</th>
                    <th className="text-left py-2 text-text-muted font-normal">Status</th>
                    <th className="text-left py-2 text-text-muted font-normal">Algorithm</th>
                    <th className="text-left py-2 text-text-muted font-normal">Created</th>
                    <th className="text-left py-2 text-text-muted font-normal">Used For</th>
                  </tr>
                </thead>
                <tbody>
                  {keys.map((key) => (
                    <tr key={key.key_id} className="border-b border-border/50 hover:bg-surface/50">
                      <td className="py-2 text-text truncate max-w-[120px]" title={key.key_id}>
                        {key.key_id.slice(0, 12)}...
                      </td>
                      <td className="py-2 text-text">v{key.version}</td>
                      <td className="py-2">
                        <StatusBadge status={key.status} />
                      </td>
                      <td className="py-2 text-text-muted">{key.algorithm}</td>
                      <td className="py-2 text-text-muted">{formatDate(key.created_at)}</td>
                      <td className="py-2 text-text-muted">{key.used_for?.join(', ') || 'All'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Compliance Information */}
        <div className="card p-4">
          <h2 className="text-lg font-theme-data text-text mb-4">Compliance Status</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-3 bg-surface rounded">
              <div className="text-xs font-theme-data text-text-muted mb-1">SOC 2 CC6.1</div>
              <div className="flex items-center gap-2">
                <StatusBadge status={health?.compliance?.soc2_compliant ? 'healthy' : 'degraded'} />
                <span className="text-sm font-theme-data text-text">Key Management</span>
              </div>
            </div>
            <div className="p-3 bg-surface rounded">
              <div className="text-xs font-theme-data text-text-muted mb-1">Rotation Policy</div>
              <div className="text-sm font-theme-data text-text">
                {health?.compliance?.key_rotation_policy || '90 days (SOC 2 recommended)'}
              </div>
            </div>
            <div className="p-3 bg-surface rounded">
              <div className="text-xs font-theme-data text-text-muted mb-1">Last Audit</div>
              <div className="text-sm font-theme-data text-text">
                {formatDate(health?.compliance?.last_audit) || 'Pending'}
              </div>
            </div>
          </div>
        </div>

        {/* Service Health */}
        {health && (
          <div className="card p-4">
            <h2 className="text-lg font-theme-data text-text mb-4">Service Health</h2>
            <div className="flex items-center gap-4">
              <StatusBadge status={health.status} />
              <span className="text-sm font-theme-data text-text">
                Encryption service{' '}
                {health.encryption_service?.available ? 'available' : 'unavailable'}
              </span>
              {health.encryption_service?.latency_ms && (
                <span className="text-sm font-theme-data text-text-muted">
                  ({health.encryption_service.latency_ms}ms latency)
                </span>
              )}
            </div>
          </div>
        )}

        {/* Secrets Scanning */}
        <div className="card p-4">
          <h2 className="text-lg font-theme-data text-text mb-4">Secrets Scanner</h2>
          <p className="text-sm text-text-muted font-theme-data mb-4">
            Scan repositories for hardcoded credentials, API keys, and sensitive data.
          </p>

          <div className="flex flex-col md:flex-row gap-4 mb-4">
            <input
              type="text"
              value={repoPath}
              onChange={(e) => setRepoPath(e.target.value)}
              placeholder="/path/to/repository"
              className="flex-1 px-3 py-2 bg-surface border border-border rounded font-theme-data text-sm text-text placeholder:text-text-muted"
            />
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={includeHistory}
                onChange={(e) => setIncludeHistory(e.target.checked)}
                className="w-4 h-4 accent-acid-green"
              />
              <span className="font-theme-data text-sm text-text-muted whitespace-nowrap">
                Scan Git History
              </span>
            </label>
            <button
              onClick={handleSecretsScan}
              disabled={secretsLoading || !repoPath.trim()}
              className="px-4 py-2 font-theme-data text-sm rounded border border-[var(--acid-cyan)]/40 bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/20 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
            >
              {secretsLoading ? 'Scanning...' : 'Scan for Secrets'}
            </button>
          </div>

          {/* Scan Results */}
          {secretsScan && (
            <div className="border-t border-border pt-4 mt-4">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <StatusBadge
                    status={secretsScan.summary.total_secrets > 0 ? 'degraded' : 'healthy'}
                  />
                  <span className="font-theme-data text-sm text-text">
                    {secretsScan.summary.total_secrets} secrets found
                  </span>
                </div>
                <span className="font-theme-data text-xs text-text-muted">
                  {secretsScan.files_scanned} files scanned
                  {secretsScan.scanned_history && ' (including history)'}
                </span>
              </div>

              {/* Severity Summary */}
              {secretsScan.summary.total_secrets > 0 && (
                <div className="grid grid-cols-4 gap-2 mb-4">
                  <div className="p-2 bg-acid-red/10 border border-acid-red/40 rounded text-center">
                    <div className="text-lg font-theme-data text-acid-red">
                      {secretsScan.summary.critical_count}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">Critical</div>
                  </div>
                  <div className="p-2 bg-acid-yellow/10 border border-acid-yellow/40 rounded text-center">
                    <div className="text-lg font-theme-data text-[var(--acid-yellow)]">
                      {secretsScan.summary.high_count}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">High</div>
                  </div>
                  <div className="p-2 bg-[var(--acid-cyan)]/10 border border-[var(--acid-cyan)]/40 rounded text-center">
                    <div className="text-lg font-theme-data text-[var(--acid-cyan)]">
                      {secretsScan.summary.medium_count}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">Medium</div>
                  </div>
                  <div className="p-2 bg-text-muted/10 border border-text-muted/40 rounded text-center">
                    <div className="text-lg font-theme-data text-text-muted">
                      {secretsScan.summary.low_count}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">Low</div>
                  </div>
                </div>
              )}

              {/* Findings Table */}
              {secretsScan.secrets.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm font-theme-data">
                    <thead>
                      <tr className="border-b border-border">
                        <th className="text-left py-2 text-text-muted font-normal">Type</th>
                        <th className="text-left py-2 text-text-muted font-normal">Severity</th>
                        <th className="text-left py-2 text-text-muted font-normal">File</th>
                        <th className="text-left py-2 text-text-muted font-normal">Line</th>
                        <th className="text-left py-2 text-text-muted font-normal">Match</th>
                      </tr>
                    </thead>
                    <tbody>
                      {secretsScan.secrets.slice(0, 20).map((secret) => (
                        <tr
                          key={secret.id}
                          className="border-b border-border/50 hover:bg-surface/50"
                        >
                          <td className="py-2 text-text">
                            {secret.secret_type.replace(/_/g, ' ')}
                            {secret.is_in_history && (
                              <span className="ml-1 text-xs text-text-muted">(history)</span>
                            )}
                          </td>
                          <td className="py-2">
                            <StatusBadge
                              status={
                                secret.severity === 'critical'
                                  ? 'unhealthy'
                                  : secret.severity === 'high'
                                    ? 'degraded'
                                    : 'healthy'
                              }
                            />
                          </td>
                          <td
                            className="py-2 text-text-muted truncate max-w-[200px]"
                            title={secret.file_path}
                          >
                            {secret.file_path}
                          </td>
                          <td className="py-2 text-text-muted">{secret.line_number}</td>
                          <td
                            className="py-2 text-[var(--acid-cyan)] truncate max-w-[150px]"
                            title={secret.matched_text}
                          >
                            {secret.matched_text}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {secretsScan.secrets.length > 20 && (
                    <div className="text-center py-2 text-text-muted text-sm font-theme-data">
                      Showing first 20 of {secretsScan.secrets.length} findings
                    </div>
                  )}
                </div>
              )}

              {secretsScan.secrets.length === 0 && (
                <div className="text-center py-4 text-[var(--accent)] font-theme-data text-sm">
                  No secrets detected in repository
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
