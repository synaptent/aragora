'use client';

import { useState, useEffect, useCallback } from 'react';

// Types matching backend models
type VulnerabilitySeverity = 'critical' | 'high' | 'medium' | 'low' | 'unknown';

interface VulnerabilityReference {
  url: string;
  source: string;
  tags: string[];
}

interface VulnerabilityFinding {
  id: string;
  title: string;
  description: string;
  severity: VulnerabilitySeverity;
  cvss_score?: number;
  cvss_vector?: string;
  package_name?: string;
  package_ecosystem?: string;
  vulnerable_versions: string[];
  patched_versions: string[];
  source: string;
  published_at?: string;
  updated_at?: string;
  references: VulnerabilityReference[];
  cwe_ids: string[];
  file_path?: string;
  line_number?: number;
  fix_available: boolean;
  recommended_version?: string;
  remediation_guidance?: string;
}

interface DependencyInfo {
  name: string;
  version: string;
  ecosystem: string;
  direct: boolean;
  dev_dependency: boolean;
  license?: string;
  vulnerabilities: VulnerabilityFinding[];
  parent?: string;
  file_path?: string;
  has_vulnerabilities: boolean;
  highest_severity?: VulnerabilitySeverity;
}

interface ScanSummary {
  total_dependencies: number;
  vulnerable_dependencies: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
}

interface ScanResult {
  scan_id: string;
  repository: string;
  branch?: string;
  commit_sha?: string;
  started_at: string;
  completed_at?: string;
  status: 'running' | 'completed' | 'failed';
  error?: string;
  dependencies: DependencyInfo[];
  vulnerabilities: VulnerabilityFinding[];
  summary: ScanSummary;
}

interface HotspotFinding {
  file_path: string;
  function_name?: string;
  class_name?: string;
  start_line: number;
  end_line: number;
  complexity: number;
  lines_of_code: number;
  cognitive_complexity?: number;
  change_frequency: number;
  last_modified?: string;
  contributors: string[];
  risk_score: number;
}

interface SecurityDashboardProps {
  apiBase: string;
  workspaceId: string;
  repositoryId?: string;
  authToken?: string;
}

const SEVERITY_CONFIG: Record<
  VulnerabilitySeverity,
  { color: string; bgColor: string; label: string }
> = {
  critical: {
    color: 'text-red-400',
    bgColor: 'bg-red-500/20 border-red-500/40',
    label: 'Critical',
  },
  high: {
    color: 'text-orange-400',
    bgColor: 'bg-orange-500/20 border-orange-500/40',
    label: 'High',
  },
  medium: {
    color: 'text-yellow-400',
    bgColor: 'bg-yellow-500/20 border-yellow-500/40',
    label: 'Medium',
  },
  low: { color: 'text-blue-400', bgColor: 'bg-blue-500/20 border-blue-500/40', label: 'Low' },
  unknown: {
    color: 'text-gray-400',
    bgColor: 'bg-gray-500/20 border-gray-500/40',
    label: 'Unknown',
  },
};

// Demo data for when API is unavailable
const DEMO_SCAN_RESULT: ScanResult = {
  scan_id: 'scan_demo_001',
  repository: 'aragora/main',
  branch: 'main',
  commit_sha: 'abc123def',
  started_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
  completed_at: new Date().toISOString(),
  status: 'completed',
  dependencies: [
    {
      name: 'lodash',
      version: '4.17.20',
      ecosystem: 'npm',
      direct: true,
      dev_dependency: false,
      license: 'MIT',
      vulnerabilities: [
        {
          id: 'CVE-2021-23337',
          title: 'Command Injection in lodash',
          description:
            'Lodash versions prior to 4.17.21 are vulnerable to Command Injection via the template function.',
          severity: 'high',
          cvss_score: 7.2,
          package_name: 'lodash',
          package_ecosystem: 'npm',
          vulnerable_versions: ['< 4.17.21'],
          patched_versions: ['4.17.21'],
          source: 'nvd',
          references: [
            { url: 'https://nvd.nist.gov/vuln/detail/CVE-2021-23337', source: 'NVD', tags: [] },
          ],
          cwe_ids: ['CWE-94'],
          fix_available: true,
          recommended_version: '4.17.21',
        },
      ],
      file_path: 'package.json',
      has_vulnerabilities: true,
      highest_severity: 'high',
    },
    {
      name: 'axios',
      version: '0.21.0',
      ecosystem: 'npm',
      direct: true,
      dev_dependency: false,
      license: 'MIT',
      vulnerabilities: [
        {
          id: 'CVE-2021-3749',
          title: 'Regular Expression Denial of Service in axios',
          description: 'axios is vulnerable to Inefficient Regular Expression Complexity.',
          severity: 'high',
          cvss_score: 7.5,
          package_name: 'axios',
          package_ecosystem: 'npm',
          vulnerable_versions: ['< 0.21.2'],
          patched_versions: ['0.21.2'],
          source: 'nvd',
          references: [],
          cwe_ids: ['CWE-1333'],
          fix_available: true,
          recommended_version: '0.21.4',
        },
      ],
      file_path: 'package.json',
      has_vulnerabilities: true,
      highest_severity: 'high',
    },
    {
      name: 'express',
      version: '4.18.2',
      ecosystem: 'npm',
      direct: true,
      dev_dependency: false,
      license: 'MIT',
      vulnerabilities: [],
      file_path: 'package.json',
      has_vulnerabilities: false,
    },
    {
      name: 'react',
      version: '18.2.0',
      ecosystem: 'npm',
      direct: true,
      dev_dependency: false,
      license: 'MIT',
      vulnerabilities: [],
      file_path: 'package.json',
      has_vulnerabilities: false,
    },
    {
      name: 'requests',
      version: '2.25.0',
      ecosystem: 'pypi',
      direct: true,
      dev_dependency: false,
      license: 'Apache-2.0',
      vulnerabilities: [
        {
          id: 'CVE-2023-32681',
          title: 'Unintended leak of Proxy-Authorization header in requests',
          description: 'Requests library leaks Proxy-Authorization header to destination server.',
          severity: 'medium',
          cvss_score: 6.1,
          package_name: 'requests',
          package_ecosystem: 'pypi',
          vulnerable_versions: ['< 2.31.0'],
          patched_versions: ['2.31.0'],
          source: 'osv',
          references: [],
          cwe_ids: ['CWE-200'],
          fix_available: true,
          recommended_version: '2.31.0',
        },
      ],
      file_path: 'requirements.txt',
      has_vulnerabilities: true,
      highest_severity: 'medium',
    },
  ],
  vulnerabilities: [],
  summary: {
    total_dependencies: 5,
    vulnerable_dependencies: 3,
    critical_count: 0,
    high_count: 2,
    medium_count: 1,
    low_count: 0,
  },
};

const DEMO_HOTSPOTS: HotspotFinding[] = [
  {
    file_path: 'src/services/auth.ts',
    function_name: 'validateToken',
    start_line: 45,
    end_line: 120,
    complexity: 15,
    lines_of_code: 75,
    cognitive_complexity: 22,
    change_frequency: 23,
    contributors: ['alice', 'bob'],
    risk_score: 78,
  },
  {
    file_path: 'src/handlers/webhook.ts',
    function_name: 'processPayload',
    start_line: 10,
    end_line: 95,
    complexity: 12,
    lines_of_code: 85,
    cognitive_complexity: 18,
    change_frequency: 15,
    contributors: ['carol'],
    risk_score: 65,
  },
  {
    file_path: 'src/utils/parser.ts',
    function_name: 'parseConfig',
    start_line: 1,
    end_line: 60,
    complexity: 8,
    lines_of_code: 60,
    cognitive_complexity: 12,
    change_frequency: 8,
    contributors: ['alice', 'dave'],
    risk_score: 45,
  },
];

type TabType = 'overview' | 'vulnerabilities' | 'dependencies' | 'hotspots';

export function SecurityDashboard({
  apiBase,
  workspaceId: _workspaceId,
  repositoryId,
  authToken,
}: SecurityDashboardProps) {
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  const [hotspots, setHotspots] = useState<HotspotFinding[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isScanning, setIsScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [severityFilter, setSeverityFilter] = useState<VulnerabilitySeverity | 'all'>('all');
  const [expandedVuln, setExpandedVuln] = useState<string | null>(null);

  const fetchScanResult = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(
        `${apiBase}/api/v1/codebase/${repositoryId || 'default'}/scan/latest`,
        { headers: authToken ? { Authorization: `Bearer ${authToken}` } : {} },
      );

      if (!response.ok) {
        // Use demo data
        setScanResult(DEMO_SCAN_RESULT);
        setHotspots(DEMO_HOTSPOTS);
        return;
      }

      const data = await response.json();
      setScanResult(data.scan_result);
    } catch {
      // Use demo data on error
      setScanResult(DEMO_SCAN_RESULT);
      setHotspots(DEMO_HOTSPOTS);
    } finally {
      setIsLoading(false);
    }
  }, [apiBase, repositoryId, authToken]);

  const fetchHotspots = useCallback(async () => {
    try {
      const response = await fetch(
        `${apiBase}/api/v1/codebase/${repositoryId || 'default'}/hotspots`,
        { headers: authToken ? { Authorization: `Bearer ${authToken}` } : {} },
      );

      if (!response.ok) {
        setHotspots(DEMO_HOTSPOTS);
        return;
      }

      const data = await response.json();
      setHotspots(data.hotspots || []);
    } catch {
      setHotspots(DEMO_HOTSPOTS);
    }
  }, [apiBase, repositoryId, authToken]);

  const triggerScan = async () => {
    setIsScanning(true);
    setError(null);

    try {
      const response = await fetch(`${apiBase}/api/v1/codebase/${repositoryId || 'default'}/scan`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
      });

      if (!response.ok) {
        // Simulate scan completion
        setTimeout(() => {
          setScanResult({
            ...DEMO_SCAN_RESULT,
            scan_id: `scan_${Date.now()}`,
            started_at: new Date().toISOString(),
            completed_at: new Date().toISOString(),
          });
          setIsScanning(false);
        }, 2000);
        return;
      }

      // Poll for completion
      const pollInterval = setInterval(async () => {
        const statusResponse = await fetch(
          `${apiBase}/api/v1/codebase/${repositoryId || 'default'}/scan/latest`,
          { headers: authToken ? { Authorization: `Bearer ${authToken}` } : {} },
        );

        if (statusResponse.ok) {
          const data = await statusResponse.json();
          if (data.scan_result?.status === 'completed' || data.scan_result?.status === 'failed') {
            clearInterval(pollInterval);
            setScanResult(data.scan_result);
            setIsScanning(false);
          }
        }
      }, 2000);

      // Timeout after 5 minutes
      setTimeout(() => {
        clearInterval(pollInterval);
        setIsScanning(false);
      }, 300000);
    } catch {
      setError('Failed to trigger scan');
      setIsScanning(false);
    }
  };

  useEffect(() => {
    fetchScanResult();
    fetchHotspots();
  }, [fetchScanResult, fetchHotspots]);

  const formatDate = (dateString?: string): string => {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleString();
  };

  const formatTimeAgo = (dateString?: string): string => {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${diffDays}d ago`;
  };

  const getVulnerableDependencies = (): DependencyInfo[] => {
    if (!scanResult) return [];
    return scanResult.dependencies.filter((d) => d.has_vulnerabilities);
  };

  const getAllVulnerabilities = (): VulnerabilityFinding[] => {
    if (!scanResult) return [];
    const vulns: VulnerabilityFinding[] = [];
    for (const dep of scanResult.dependencies) {
      for (const vuln of dep.vulnerabilities) {
        vulns.push({ ...vuln, package_name: dep.name, package_ecosystem: dep.ecosystem });
      }
    }
    return vulns;
  };

  const filteredVulnerabilities = getAllVulnerabilities().filter(
    (v) => severityFilter === 'all' || v.severity === severityFilter,
  );

  if (isLoading) {
    return (
      <div className="border border-[var(--accent)]/30 bg-surface/50 p-4 rounded">
        <div className="text-center py-8 text-text-muted font-theme-data text-sm animate-pulse">
          Loading security dashboard...
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-[var(--accent)]/30 p-4 bg-surface/50">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-theme-data text-[var(--accent)]">Security Dashboard</h2>
            {scanResult && (
              <div className="text-xs text-text-muted mt-1">
                Repository: <span className="text-[var(--acid-cyan)]">{scanResult.repository}</span>
                {scanResult.branch && <span> / {scanResult.branch}</span>}
                {scanResult.commit_sha && (
                  <span className="ml-2 font-theme-data">
                    ({scanResult.commit_sha.slice(0, 7)})
                  </span>
                )}
              </div>
            )}
          </div>
          <div className="flex items-center gap-3">
            {scanResult && (
              <div className="text-xs text-text-muted">
                Last scan: {formatTimeAgo(scanResult.completed_at)}
              </div>
            )}
            <button
              onClick={triggerScan}
              disabled={isScanning}
              className={`px-4 py-2 text-sm font-theme-data rounded transition-colors ${
                isScanning
                  ? 'bg-[var(--accent)]/20 text-[var(--accent)]/50 cursor-not-allowed'
                  : 'bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80'
              }`}
            >
              {isScanning ? 'Scanning...' : 'Run Scan'}
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-2">
          {(['overview', 'vulnerabilities', 'dependencies', 'hotspots'] as TabType[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-sm font-theme-data rounded-t transition-colors ${
                activeTab === tab
                  ? 'bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] border-b-0'
                  : 'bg-surface/50 border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)]'
              }`}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="p-3 bg-red-500/10 border-b border-red-500/30 text-red-400 text-sm font-theme-data">
          {error}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {/* Overview Tab */}
        {activeTab === 'overview' && scanResult && (
          <div className="space-y-6">
            {/* Summary Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="p-4 border border-[var(--accent)]/30 rounded bg-surface/30">
                <div className="text-2xl font-theme-data text-[var(--accent)]">
                  {scanResult.summary.total_dependencies}
                </div>
                <div className="text-xs text-text-muted mt-1">Total Dependencies</div>
              </div>
              <div className="p-4 border border-red-500/30 rounded bg-surface/30">
                <div className="text-2xl font-theme-data text-red-400">
                  {scanResult.summary.vulnerable_dependencies}
                </div>
                <div className="text-xs text-text-muted mt-1">Vulnerable</div>
              </div>
              <div className="p-4 border border-[var(--accent)]/30 rounded bg-surface/30">
                <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                  {scanResult.dependencies.filter((d) => d.direct).length}
                </div>
                <div className="text-xs text-text-muted mt-1">Direct Dependencies</div>
              </div>
              <div className="p-4 border border-[var(--accent)]/30 rounded bg-surface/30">
                <div className="text-2xl font-theme-data text-purple-400">
                  {new Set(scanResult.dependencies.map((d) => d.ecosystem)).size}
                </div>
                <div className="text-xs text-text-muted mt-1">Ecosystems</div>
              </div>
            </div>

            {/* Severity Breakdown */}
            <div className="border border-[var(--accent)]/30 rounded p-4 bg-surface/30">
              <h3 className="text-sm font-theme-data text-[var(--accent)] mb-4">
                Vulnerability Severity
              </h3>
              <div className="grid grid-cols-4 gap-4">
                <div className="text-center">
                  <div className={`text-3xl font-theme-data ${SEVERITY_CONFIG.critical.color}`}>
                    {scanResult.summary.critical_count}
                  </div>
                  <div className="text-xs text-text-muted mt-1">Critical</div>
                </div>
                <div className="text-center">
                  <div className={`text-3xl font-theme-data ${SEVERITY_CONFIG.high.color}`}>
                    {scanResult.summary.high_count}
                  </div>
                  <div className="text-xs text-text-muted mt-1">High</div>
                </div>
                <div className="text-center">
                  <div className={`text-3xl font-theme-data ${SEVERITY_CONFIG.medium.color}`}>
                    {scanResult.summary.medium_count}
                  </div>
                  <div className="text-xs text-text-muted mt-1">Medium</div>
                </div>
                <div className="text-center">
                  <div className={`text-3xl font-theme-data ${SEVERITY_CONFIG.low.color}`}>
                    {scanResult.summary.low_count}
                  </div>
                  <div className="text-xs text-text-muted mt-1">Low</div>
                </div>
              </div>
            </div>

            {/* Quick Actions */}
            {scanResult.summary.vulnerable_dependencies > 0 && (
              <div className="border border-orange-500/30 rounded p-4 bg-orange-500/5">
                <h3 className="text-sm font-theme-data text-orange-400 mb-3">
                  Recommended Actions
                </h3>
                <div className="space-y-2">
                  {getVulnerableDependencies()
                    .slice(0, 3)
                    .map((dep) => (
                      <div
                        key={`${dep.name}-${dep.version}`}
                        className="flex items-center justify-between p-2 bg-surface/50 rounded"
                      >
                        <div className="flex items-center gap-2">
                          <span
                            className={`px-2 py-0.5 text-xs rounded border ${SEVERITY_CONFIG[dep.highest_severity || 'unknown'].bgColor}`}
                          >
                            {dep.highest_severity}
                          </span>
                          <span className="font-theme-data text-sm">
                            {dep.name}@{dep.version}
                          </span>
                        </div>
                        {dep.vulnerabilities[0]?.fix_available && (
                          <span className="text-xs text-[var(--accent)]">
                            Upgrade to {dep.vulnerabilities[0].recommended_version}
                          </span>
                        )}
                      </div>
                    ))}
                </div>
              </div>
            )}

            {/* Scan Info */}
            <div className="border border-[var(--accent)]/30 rounded p-4 bg-surface/30">
              <h3 className="text-sm font-theme-data text-[var(--accent)] mb-3">Scan Details</h3>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-text-muted">Scan ID:</span>
                  <span className="ml-2 font-theme-data">{scanResult.scan_id}</span>
                </div>
                <div>
                  <span className="text-text-muted">Status:</span>
                  <span
                    className={`ml-2 font-theme-data ${
                      scanResult.status === 'completed'
                        ? 'text-green-400'
                        : scanResult.status === 'failed'
                          ? 'text-red-400'
                          : 'text-yellow-400'
                    }`}
                  >
                    {scanResult.status}
                  </span>
                </div>
                <div>
                  <span className="text-text-muted">Started:</span>
                  <span className="ml-2">{formatDate(scanResult.started_at)}</span>
                </div>
                <div>
                  <span className="text-text-muted">Completed:</span>
                  <span className="ml-2">{formatDate(scanResult.completed_at)}</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Vulnerabilities Tab */}
        {activeTab === 'vulnerabilities' && (
          <div className="space-y-4">
            {/* Filter */}
            <div className="flex items-center gap-2 mb-4">
              <span className="text-xs text-text-muted">Filter by severity:</span>
              <div className="flex gap-1">
                <button
                  onClick={() => setSeverityFilter('all')}
                  className={`px-3 py-1 text-xs font-theme-data rounded ${
                    severityFilter === 'all'
                      ? 'bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)]'
                      : 'bg-surface border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)]'
                  }`}
                >
                  All ({getAllVulnerabilities().length})
                </button>
                {(['critical', 'high', 'medium', 'low'] as VulnerabilitySeverity[]).map((sev) => {
                  const count = getAllVulnerabilities().filter((v) => v.severity === sev).length;
                  return (
                    <button
                      key={sev}
                      onClick={() => setSeverityFilter(sev)}
                      className={`px-3 py-1 text-xs font-theme-data rounded ${
                        severityFilter === sev
                          ? `${SEVERITY_CONFIG[sev].bgColor} ${SEVERITY_CONFIG[sev].color} border`
                          : 'bg-surface border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)]'
                      }`}
                    >
                      {sev} ({count})
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Vulnerability List */}
            {filteredVulnerabilities.length === 0 ? (
              <div className="text-center py-8 text-text-muted font-theme-data text-sm">
                No vulnerabilities found matching your filter.
              </div>
            ) : (
              <div className="space-y-3">
                {filteredVulnerabilities.map((vuln, idx) => {
                  const isExpanded = expandedVuln === `${vuln.id}-${idx}`;
                  return (
                    <div
                      key={`${vuln.id}-${idx}`}
                      className={`border rounded transition-colors ${SEVERITY_CONFIG[vuln.severity].bgColor}`}
                    >
                      <button
                        onClick={() => setExpandedVuln(isExpanded ? null : `${vuln.id}-${idx}`)}
                        className="w-full p-4 text-left"
                      >
                        <div className="flex items-start justify-between">
                          <div className="flex-1">
                            <div className="flex items-center gap-2 mb-1">
                              <span
                                className={`px-2 py-0.5 text-xs font-theme-data rounded border ${SEVERITY_CONFIG[vuln.severity].bgColor} ${SEVERITY_CONFIG[vuln.severity].color}`}
                              >
                                {vuln.severity.toUpperCase()}
                              </span>
                              <span className="font-theme-data text-sm text-[var(--acid-cyan)]">
                                {vuln.id}
                              </span>
                              {vuln.cvss_score && (
                                <span className="text-xs text-text-muted">
                                  CVSS: {vuln.cvss_score.toFixed(1)}
                                </span>
                              )}
                            </div>
                            <h4 className="text-sm font-theme-data">{vuln.title}</h4>
                            <div className="text-xs text-text-muted mt-1">
                              Package:{' '}
                              <span className="text-[var(--accent)]">{vuln.package_name}</span>
                              <span className="mx-1">|</span>
                              Ecosystem: {vuln.package_ecosystem}
                            </div>
                          </div>
                          <div className="text-xs text-text-muted ml-4">
                            {isExpanded ? '[-]' : '[+]'}
                          </div>
                        </div>
                      </button>

                      {isExpanded && (
                        <div className="px-4 pb-4 border-t border-[var(--accent)]/20 mt-2 pt-4 space-y-3">
                          <div>
                            <span className="text-xs text-text-muted block mb-1">Description</span>
                            <p className="text-sm">{vuln.description}</p>
                          </div>

                          {vuln.vulnerable_versions.length > 0 && (
                            <div>
                              <span className="text-xs text-text-muted block mb-1">
                                Vulnerable Versions
                              </span>
                              <p className="text-sm font-theme-data text-red-400">
                                {vuln.vulnerable_versions.join(', ')}
                              </p>
                            </div>
                          )}

                          {vuln.fix_available && vuln.recommended_version && (
                            <div className="p-3 bg-green-500/10 border border-green-500/30 rounded">
                              <span className="text-xs text-green-400 block mb-1">
                                Fix Available
                              </span>
                              <p className="text-sm font-theme-data">
                                Upgrade to version{' '}
                                <span className="text-green-400">{vuln.recommended_version}</span>
                              </p>
                            </div>
                          )}

                          {vuln.cwe_ids.length > 0 && (
                            <div>
                              <span className="text-xs text-text-muted block mb-1">CWE</span>
                              <div className="flex gap-2">
                                {vuln.cwe_ids.map((cwe) => (
                                  <span
                                    key={cwe}
                                    className="px-2 py-0.5 text-xs bg-purple-500/20 text-purple-400 rounded"
                                  >
                                    {cwe}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}

                          {vuln.references.length > 0 && (
                            <div>
                              <span className="text-xs text-text-muted block mb-1">References</span>
                              <div className="space-y-1">
                                {vuln.references.map((ref, i) => (
                                  <a
                                    key={i}
                                    href={ref.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="block text-xs text-[var(--acid-cyan)] hover:underline truncate"
                                  >
                                    [{ref.source}] {ref.url}
                                  </a>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Dependencies Tab */}
        {activeTab === 'dependencies' && scanResult && (
          <div className="space-y-4">
            {/* Group by ecosystem */}
            {Array.from(new Set(scanResult.dependencies.map((d) => d.ecosystem))).map(
              (ecosystem) => {
                const deps = scanResult.dependencies.filter((d) => d.ecosystem === ecosystem);
                const vulnCount = deps.filter((d) => d.has_vulnerabilities).length;

                return (
                  <div key={ecosystem} className="border border-[var(--accent)]/30 rounded">
                    <div className="p-3 bg-surface/50 border-b border-[var(--accent)]/20 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-theme-data text-sm text-[var(--accent)]">
                          {ecosystem}
                        </span>
                        <span className="text-xs text-text-muted">({deps.length} packages)</span>
                      </div>
                      {vulnCount > 0 && (
                        <span className="px-2 py-0.5 text-xs bg-red-500/20 text-red-400 rounded">
                          {vulnCount} vulnerable
                        </span>
                      )}
                    </div>
                    <div className="divide-y divide-acid-green/10">
                      {deps.map((dep) => (
                        <div
                          key={`${dep.name}-${dep.version}`}
                          className={`p-3 flex items-center justify-between ${
                            dep.has_vulnerabilities ? 'bg-red-500/5' : ''
                          }`}
                        >
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="font-theme-data text-sm">{dep.name}</span>
                              <span className="text-xs text-text-muted">@{dep.version}</span>
                              {dep.dev_dependency && (
                                <span className="px-1.5 py-0.5 text-xs bg-gray-500/20 text-gray-400 rounded">
                                  dev
                                </span>
                              )}
                              {!dep.direct && (
                                <span className="px-1.5 py-0.5 text-xs bg-blue-500/20 text-blue-400 rounded">
                                  transitive
                                </span>
                              )}
                            </div>
                            {dep.license && (
                              <div className="text-xs text-text-muted mt-1">{dep.license}</div>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            {dep.has_vulnerabilities ? (
                              <span
                                className={`px-2 py-0.5 text-xs rounded border ${SEVERITY_CONFIG[dep.highest_severity || 'unknown'].bgColor} ${SEVERITY_CONFIG[dep.highest_severity || 'unknown'].color}`}
                              >
                                {dep.vulnerabilities.length} vuln
                                {dep.vulnerabilities.length !== 1 ? 's' : ''}
                              </span>
                            ) : (
                              <span className="text-xs text-green-400">Secure</span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              },
            )}
          </div>
        )}

        {/* Hotspots Tab */}
        {activeTab === 'hotspots' && (
          <div className="space-y-4">
            <p className="text-sm text-text-muted mb-4">
              Code hotspots are areas with high complexity and frequent changes, which often
              indicate security risk.
            </p>

            {hotspots.length === 0 ? (
              <div className="text-center py-8 text-text-muted font-theme-data text-sm">
                No complexity hotspots detected.
              </div>
            ) : (
              <div className="space-y-3">
                {hotspots.map((hotspot, idx) => {
                  const riskColor =
                    hotspot.risk_score >= 70
                      ? 'text-red-400'
                      : hotspot.risk_score >= 50
                        ? 'text-orange-400'
                        : hotspot.risk_score >= 30
                          ? 'text-yellow-400'
                          : 'text-green-400';

                  return (
                    <div
                      key={idx}
                      className="border border-[var(--accent)]/30 rounded p-4 bg-surface/30"
                    >
                      <div className="flex items-start justify-between mb-3">
                        <div>
                          <div className="font-theme-data text-sm text-[var(--acid-cyan)]">
                            {hotspot.file_path}:{hotspot.start_line}-{hotspot.end_line}
                          </div>
                          {hotspot.function_name && (
                            <div className="text-xs text-text-muted mt-1">
                              Function:{' '}
                              <span className="text-[var(--accent)]">{hotspot.function_name}</span>
                              {hotspot.class_name && (
                                <span className="ml-2">in {hotspot.class_name}</span>
                              )}
                            </div>
                          )}
                        </div>
                        <div className="text-right">
                          <div className={`text-2xl font-theme-data ${riskColor}`}>
                            {hotspot.risk_score.toFixed(0)}
                          </div>
                          <div className="text-xs text-text-muted">Risk Score</div>
                        </div>
                      </div>

                      <div className="grid grid-cols-4 gap-4 text-sm">
                        <div>
                          <div className="text-text-muted text-xs">Complexity</div>
                          <div className="font-theme-data">{hotspot.complexity}</div>
                        </div>
                        <div>
                          <div className="text-text-muted text-xs">Cognitive</div>
                          <div className="font-theme-data">
                            {hotspot.cognitive_complexity || 'N/A'}
                          </div>
                        </div>
                        <div>
                          <div className="text-text-muted text-xs">Lines</div>
                          <div className="font-theme-data">{hotspot.lines_of_code}</div>
                        </div>
                        <div>
                          <div className="text-text-muted text-xs">Changes</div>
                          <div className="font-theme-data">{hotspot.change_frequency}</div>
                        </div>
                      </div>

                      {hotspot.contributors.length > 0 && (
                        <div className="mt-3 flex items-center gap-2">
                          <span className="text-xs text-text-muted">Contributors:</span>
                          {hotspot.contributors.map((contributor) => (
                            <span
                              key={contributor}
                              className="px-2 py-0.5 text-xs bg-[var(--accent)]/10 text-[var(--accent)] rounded"
                            >
                              {contributor}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default SecurityDashboard;
