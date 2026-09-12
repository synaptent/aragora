'use client';

import { useState, useCallback } from 'react';
import { API_BASE_URL } from '@/config';

interface Vulnerability {
  id: string;
  title: string;
  description: string;
  affected_package: string;
  affected_versions: string;
  fixed_version: string | null;
  cvss_score: number | null;
  cwe_id: string | null;
  references: string[];
}

interface LicenseConflict {
  package: string;
  license: string;
  conflict_type: string;
  severity: string;
  description: string;
}

interface DependencyInfo {
  name: string;
  version: string;
  type: string;
  package_manager: string;
  license: string;
  purl: string;
}

interface ScanResult {
  project_name: string;
  total_vulnerabilities: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  vulnerabilities_by_severity: {
    critical: Vulnerability[];
    high: Vulnerability[];
    medium: Vulnerability[];
    low: Vulnerability[];
  };
  scan_summary: { packages_scanned: number; packages_with_vulnerabilities: number };
}

interface DependencyAnalysis {
  project_name: string;
  project_version: string;
  package_managers: string[];
  total_dependencies: number;
  direct_dependencies: number;
  transitive_dependencies: number;
  dev_dependencies: number;
  dependencies: DependencyInfo[];
}

interface DependencySecurityPanelProps {
  apiBase?: string;
  userId?: string;
  authToken?: string;
  repoPath?: string;
  className?: string;
}

export function DependencySecurityPanel({
  apiBase: apiBaseProp,
  repoPath = '',
  className = '',
}: DependencySecurityPanelProps) {
  const apiBase = apiBaseProp ?? API_BASE_URL;
  const [path, setPath] = useState(repoPath);
  const [analysis, setAnalysis] = useState<DependencyAnalysis | null>(null);
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  const [licenseConflicts, setLicenseConflicts] = useState<LicenseConflict[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'overview' | 'vulnerabilities' | 'licenses' | 'sbom'>(
    'overview',
  );
  const [sbomFormat, setSbomFormat] = useState<'cyclonedx' | 'spdx'>('cyclonedx');
  const [sbomContent, setSbomContent] = useState<string | null>(null);

  const analyzeDependencies = useCallback(async () => {
    if (!path) {
      setError('Please enter a repository path');
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const res = await fetch(`${apiBase}/api/v1/codebase/analyze-dependencies`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_path: path, include_dev: true }),
      });

      const data = await res.json();
      if (data.status === 'success') {
        setAnalysis(data.data);
      } else {
        setError(data.message || 'Analysis failed');
      }
    } catch {
      setError('Failed to analyze dependencies');
    } finally {
      setLoading(false);
    }
  }, [path, apiBase]);

  const scanVulnerabilities = useCallback(async () => {
    if (!path) return;

    try {
      setLoading(true);
      setError(null);

      const res = await fetch(`${apiBase}/api/v1/codebase/scan-vulnerabilities`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_path: path }),
      });

      const data = await res.json();
      if (data.status === 'success') {
        setScanResult(data.data);
        setActiveTab('vulnerabilities');
      } else {
        setError(data.message || 'Scan failed');
      }
    } catch {
      setError('Failed to scan for vulnerabilities');
    } finally {
      setLoading(false);
    }
  }, [path, apiBase]);

  const checkLicenses = useCallback(async () => {
    if (!path) return;

    try {
      setLoading(true);
      setError(null);

      const res = await fetch(`${apiBase}/api/v1/codebase/check-licenses`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_path: path, project_license: 'MIT' }),
      });

      const data = await res.json();
      if (data.status === 'success') {
        setLicenseConflicts(data.data.conflicts);
        setActiveTab('licenses');
      } else {
        setError(data.message || 'License check failed');
      }
    } catch {
      setError('Failed to check licenses');
    } finally {
      setLoading(false);
    }
  }, [path, apiBase]);

  const generateSbom = useCallback(async () => {
    if (!path) return;

    try {
      setLoading(true);
      setError(null);

      const res = await fetch(`${apiBase}/api/v1/codebase/sbom`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo_path: path,
          format: sbomFormat,
          include_vulnerabilities: true,
        }),
      });

      const data = await res.json();
      if (data.status === 'success') {
        setSbomContent(data.data.sbom_json);
        setActiveTab('sbom');
      } else {
        setError(data.message || 'SBOM generation failed');
      }
    } catch {
      setError('Failed to generate SBOM');
    } finally {
      setLoading(false);
    }
  }, [path, sbomFormat, apiBase]);

  const downloadSbom = () => {
    if (!sbomContent) return;
    const blob = new Blob([sbomContent], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `sbom-${sbomFormat}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'critical':
        return 'bg-red-600 text-white';
      case 'high':
        return 'bg-red-500 text-white';
      case 'medium':
        return 'bg-yellow-500 text-black';
      case 'low':
        return 'bg-blue-500 text-white';
      default:
        return 'bg-gray-500 text-white';
    }
  };

  return (
    <div className={`bg-[var(--surface)] border border-[var(--border)] rounded ${className}`}>
      {/* Header */}
      <div className="p-4 border-b border-[var(--border)]">
        <h3 className="font-theme-data text-sm font-medium text-[var(--text)] mb-3">
          Dependency Security Analysis
        </h3>

        {/* Path Input */}
        <div className="flex items-center gap-2 mb-3">
          <input
            type="text"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="/path/to/repository"
            className="flex-1 px-3 py-2 text-sm font-theme-data bg-[var(--surface)] border border-[var(--border)] rounded text-[var(--text)] placeholder:text-[var(--text-muted)]"
          />
          <button
            onClick={analyzeDependencies}
            disabled={loading || !path}
            className="px-4 py-2 text-sm font-theme-data bg-[var(--primary)] text-white rounded hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {loading ? 'Analyzing...' : 'Analyze'}
          </button>
        </div>

        {/* Action Buttons */}
        {analysis && (
          <div className="flex items-center gap-2">
            <button
              onClick={scanVulnerabilities}
              disabled={loading}
              className="px-3 py-1 text-xs font-theme-data text-red-400 border border-red-400/40 rounded hover:bg-red-500/20 transition-colors"
            >
              Scan CVEs
            </button>
            <button
              onClick={checkLicenses}
              disabled={loading}
              className="px-3 py-1 text-xs font-theme-data text-yellow-400 border border-yellow-400/40 rounded hover:bg-yellow-500/20 transition-colors"
            >
              Check Licenses
            </button>
            <button
              onClick={generateSbom}
              disabled={loading}
              className="px-3 py-1 text-xs font-theme-data text-blue-400 border border-blue-400/40 rounded hover:bg-blue-500/20 transition-colors"
            >
              Generate SBOM
            </button>
          </div>
        )}
      </div>

      {/* Tabs */}
      {analysis && (
        <div className="flex border-b border-[var(--border)]">
          {(['overview', 'vulnerabilities', 'licenses', 'sbom'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-xs font-theme-data transition-colors ${
                activeTab === tab
                  ? 'text-[var(--primary)] border-b-2 border-[var(--primary)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)]'
              }`}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
              {tab === 'vulnerabilities' && scanResult && (
                <span className="ml-1 text-red-400">({scanResult.total_vulnerabilities})</span>
              )}
              {tab === 'licenses' && licenseConflicts.length > 0 && (
                <span className="ml-1 text-yellow-400">({licenseConflicts.length})</span>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Content */}
      <div className="p-4 max-h-[500px] overflow-y-auto">
        {error && (
          <div className="mb-4 p-3 bg-red-500/20 border border-red-500/40 rounded text-red-400 text-sm font-theme-data">
            {error}
          </div>
        )}

        {loading && (
          <div className="text-center py-8 text-[var(--text-muted)] text-sm font-theme-data">
            {activeTab === 'vulnerabilities'
              ? 'Scanning for vulnerabilities...'
              : activeTab === 'licenses'
                ? 'Checking license compatibility...'
                : activeTab === 'sbom'
                  ? 'Generating SBOM...'
                  : 'Analyzing dependencies...'}
          </div>
        )}

        {!loading && !analysis && (
          <div className="text-center py-8 text-[var(--text-muted)] text-sm font-theme-data">
            Enter a repository path and click Analyze to begin
          </div>
        )}

        {/* Overview Tab */}
        {!loading && analysis && activeTab === 'overview' && (
          <div className="space-y-4">
            {/* Summary Stats */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="p-3 bg-[var(--surface-hover)] rounded">
                <div className="text-2xl font-theme-data text-[var(--text)]">
                  {analysis.total_dependencies}
                </div>
                <div className="text-xs text-[var(--text-muted)]">Total Dependencies</div>
              </div>
              <div className="p-3 bg-[var(--surface-hover)] rounded">
                <div className="text-2xl font-theme-data text-blue-400">
                  {analysis.direct_dependencies}
                </div>
                <div className="text-xs text-[var(--text-muted)]">Direct</div>
              </div>
              <div className="p-3 bg-[var(--surface-hover)] rounded">
                <div className="text-2xl font-theme-data text-purple-400">
                  {analysis.transitive_dependencies}
                </div>
                <div className="text-xs text-[var(--text-muted)]">Transitive</div>
              </div>
              <div className="p-3 bg-[var(--surface-hover)] rounded">
                <div className="text-2xl font-theme-data text-gray-400">
                  {analysis.dev_dependencies}
                </div>
                <div className="text-xs text-[var(--text-muted)]">Dev Only</div>
              </div>
            </div>

            {/* Project Info */}
            <div className="p-3 border border-[var(--border)] rounded">
              <div className="text-sm font-theme-data text-[var(--text)]">
                {analysis.project_name}@{analysis.project_version}
              </div>
              <div className="text-xs text-[var(--text-muted)] mt-1">
                Package managers: {analysis.package_managers.join(', ')}
              </div>
            </div>

            {/* Dependency List */}
            <div>
              <h4 className="text-xs font-theme-data text-[var(--text-muted)] mb-2">
                DEPENDENCIES ({analysis.dependencies.length} shown)
              </h4>
              <div className="space-y-1 max-h-[200px] overflow-y-auto">
                {analysis.dependencies.slice(0, 50).map((dep, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between p-2 bg-[var(--surface-hover)] rounded text-xs font-theme-data"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-[var(--text)]">{dep.name}</span>
                      <span className="text-[var(--text-muted)]">@{dep.version}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={`px-1.5 py-0.5 rounded ${dep.type === 'direct' ? 'bg-blue-500/20 text-blue-400' : 'bg-purple-500/20 text-purple-400'}`}
                      >
                        {dep.type}
                      </span>
                      {dep.license && (
                        <span className="text-[var(--text-muted)]">{dep.license}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Vulnerabilities Tab */}
        {!loading && activeTab === 'vulnerabilities' && scanResult && (
          <div className="space-y-4">
            {/* Severity Summary */}
            <div className="flex items-center gap-4">
              {scanResult.critical_count > 0 && (
                <span className="px-2 py-1 text-xs font-theme-data bg-red-600 text-white rounded">
                  {scanResult.critical_count} Critical
                </span>
              )}
              {scanResult.high_count > 0 && (
                <span className="px-2 py-1 text-xs font-theme-data bg-red-500 text-white rounded">
                  {scanResult.high_count} High
                </span>
              )}
              {scanResult.medium_count > 0 && (
                <span className="px-2 py-1 text-xs font-theme-data bg-yellow-500 text-black rounded">
                  {scanResult.medium_count} Medium
                </span>
              )}
              {scanResult.low_count > 0 && (
                <span className="px-2 py-1 text-xs font-theme-data bg-blue-500 text-white rounded">
                  {scanResult.low_count} Low
                </span>
              )}
              {scanResult.total_vulnerabilities === 0 && (
                <span className="px-2 py-1 text-xs font-theme-data bg-green-500 text-white rounded">
                  No vulnerabilities found
                </span>
              )}
            </div>

            {/* Vulnerability List */}
            {['critical', 'high', 'medium', 'low'].map((severity) => {
              const vulns =
                scanResult.vulnerabilities_by_severity[
                  severity as keyof typeof scanResult.vulnerabilities_by_severity
                ];
              if (!vulns || vulns.length === 0) return null;

              return (
                <div key={severity}>
                  <h4 className="text-xs font-theme-data text-[var(--text-muted)] mb-2 uppercase">
                    {severity} ({vulns.length})
                  </h4>
                  <div className="space-y-2">
                    {vulns.map((vuln, i) => (
                      <div key={i} className="p-3 border border-[var(--border)] rounded">
                        <div className="flex items-start justify-between mb-2">
                          <div>
                            <span
                              className={`px-1.5 py-0.5 text-xs font-theme-data rounded ${getSeverityColor(severity)}`}
                            >
                              {vuln.id}
                            </span>
                            {vuln.cvss_score && (
                              <span className="ml-2 text-xs text-[var(--text-muted)]">
                                CVSS: {vuln.cvss_score}
                              </span>
                            )}
                          </div>
                          <span className="text-xs font-theme-data text-[var(--text-muted)]">
                            {vuln.affected_package}
                          </span>
                        </div>
                        <p className="text-sm text-[var(--text)] mb-2">{vuln.title}</p>
                        <div className="text-xs text-[var(--text-muted)]">
                          Affected: {vuln.affected_versions}
                          {vuln.fixed_version && (
                            <span className="ml-2 text-green-400">Fix: {vuln.fixed_version}</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Licenses Tab */}
        {!loading && activeTab === 'licenses' && (
          <div className="space-y-4">
            {licenseConflicts.length === 0 ? (
              <div className="text-center py-8 text-green-400 text-sm font-theme-data">
                No license conflicts detected
              </div>
            ) : (
              <div className="space-y-2">
                {licenseConflicts.map((conflict, i) => (
                  <div
                    key={i}
                    className={`p-3 border rounded ${
                      conflict.severity === 'error'
                        ? 'border-red-500/40 bg-red-500/10'
                        : conflict.severity === 'warning'
                          ? 'border-yellow-500/40 bg-yellow-500/10'
                          : 'border-[var(--border)]'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-theme-data text-[var(--text)]">
                        {conflict.package}
                      </span>
                      <span
                        className={`px-1.5 py-0.5 text-xs rounded ${
                          conflict.severity === 'error'
                            ? 'bg-red-500/20 text-red-400'
                            : conflict.severity === 'warning'
                              ? 'bg-yellow-500/20 text-yellow-400'
                              : 'bg-gray-500/20 text-gray-400'
                        }`}
                      >
                        {conflict.severity}
                      </span>
                    </div>
                    <div className="text-xs text-[var(--text-muted)] mb-1">
                      License: {conflict.license} ({conflict.conflict_type})
                    </div>
                    <p className="text-xs text-[var(--text-muted)]">{conflict.description}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* SBOM Tab */}
        {!loading && activeTab === 'sbom' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <select
                  value={sbomFormat}
                  onChange={(e) => setSbomFormat(e.target.value as 'cyclonedx' | 'spdx')}
                  className="px-2 py-1 text-xs font-theme-data bg-[var(--surface)] border border-[var(--border)] rounded text-[var(--text)]"
                >
                  <option value="cyclonedx">CycloneDX</option>
                  <option value="spdx">SPDX</option>
                </select>
                <button
                  onClick={generateSbom}
                  className="px-2 py-1 text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--text)] border border-[var(--border)] rounded"
                >
                  Regenerate
                </button>
              </div>
              {sbomContent && (
                <button
                  onClick={downloadSbom}
                  className="px-3 py-1 text-xs font-theme-data text-blue-400 border border-blue-400/40 rounded hover:bg-blue-500/20"
                >
                  Download JSON
                </button>
              )}
            </div>

            {sbomContent ? (
              <pre className="p-3 bg-[var(--surface-hover)] rounded text-xs font-theme-data text-[var(--text)] overflow-x-auto max-h-[300px]">
                {sbomContent.slice(0, 5000)}
                {sbomContent.length > 5000 && '\n... (truncated)'}
              </pre>
            ) : (
              <div className="text-center py-8 text-[var(--text-muted)] text-sm font-theme-data">
                Click "Generate SBOM" to create a Software Bill of Materials
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default DependencySecurityPanel;
