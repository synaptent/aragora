'use client';

import { useState } from 'react';

interface Finding {
  id: string;
  title: string;
  description: string;
  category: string;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  confidence: number;
  file_path: string;
  line_number: number;
  code_snippet?: string;
  cwe_id?: string;
  recommendation?: string;
}

interface ScanResult {
  scan_id: string;
  status: string;
  repository: string;
  files_scanned: number;
  lines_scanned?: number;
  risk_score?: number;
  summary: { critical: number; high: number; medium: number; low: number; info?: number };
  findings: Finding[];
}

interface FindingsSummaryProps {
  result: ScanResult;
}

type SeverityFilter = 'all' | 'critical' | 'high' | 'medium' | 'low';

const SEVERITY_CONFIG: Record<string, { color: string; bgColor: string; label: string }> = {
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
  info: { color: 'text-gray-400', bgColor: 'bg-gray-500/20 border-gray-500/40', label: 'Info' },
};

export function FindingsSummary({ result }: FindingsSummaryProps) {
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all');
  const [expandedFinding, setExpandedFinding] = useState<string | null>(null);

  const filteredFindings = result.findings.filter(
    (f) => severityFilter === 'all' || f.severity === severityFilter,
  );

  const totalFindings =
    result.summary.critical +
    result.summary.high +
    result.summary.medium +
    result.summary.low +
    (result.summary.info || 0);

  const getRiskLevel = (score: number): { label: string; color: string } => {
    if (score >= 70) return { label: 'High Risk', color: 'text-red-400' };
    if (score >= 40) return { label: 'Medium Risk', color: 'text-yellow-400' };
    if (score >= 10) return { label: 'Low Risk', color: 'text-blue-400' };
    return { label: 'Minimal Risk', color: 'text-green-400' };
  };

  const riskLevel = result.risk_score !== undefined ? getRiskLevel(result.risk_score) : null;

  return (
    <div className="space-y-6">
      {/* Summary Header */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-6">
        <div className="flex items-start justify-between mb-6">
          <div>
            <h3 className="text-lg font-theme-data text-[var(--acid-green)]">
              {'>'} SCAN COMPLETE
            </h3>
            <p className="text-sm text-[var(--text-muted)] mt-1">
              Repository: <span className="text-[var(--acid-cyan)]">{result.repository}</span>
            </p>
          </div>
          {riskLevel && result.risk_score !== undefined && (
            <div className="text-right">
              <div className={`text-3xl font-theme-data ${riskLevel.color}`}>
                {result.risk_score.toFixed(0)}
              </div>
              <div className={`text-xs ${riskLevel.color}`}>{riskLevel.label}</div>
            </div>
          )}
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <StatCard
            label="Files Scanned"
            value={result.files_scanned}
            color="text-[var(--acid-cyan)]"
          />
          {result.lines_scanned && (
            <StatCard
              label="Lines Analyzed"
              value={result.lines_scanned.toLocaleString()}
              color="text-[var(--text)]"
            />
          )}
          <StatCard
            label="Total Findings"
            value={totalFindings}
            color={totalFindings > 0 ? 'text-yellow-400' : 'text-green-400'}
          />
          <StatCard
            label="Critical/High"
            value={result.summary.critical + result.summary.high}
            color={
              result.summary.critical + result.summary.high > 0 ? 'text-red-400' : 'text-green-400'
            }
            pulse={result.summary.critical > 0}
          />
          <StatCard
            label="Scan ID"
            value={result.scan_id.slice(-8)}
            color="text-[var(--text-muted)]"
            small
          />
        </div>
      </div>

      {/* Severity Breakdown */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
        <h4 className="text-sm font-theme-data text-[var(--acid-green)] mb-4">
          Severity Breakdown
        </h4>
        <div className="flex gap-2 flex-wrap">
          <FilterButton
            active={severityFilter === 'all'}
            onClick={() => setSeverityFilter('all')}
            color="default"
          >
            All ({totalFindings})
          </FilterButton>
          <FilterButton
            active={severityFilter === 'critical'}
            onClick={() => setSeverityFilter('critical')}
            color="critical"
          >
            Critical ({result.summary.critical})
          </FilterButton>
          <FilterButton
            active={severityFilter === 'high'}
            onClick={() => setSeverityFilter('high')}
            color="high"
          >
            High ({result.summary.high})
          </FilterButton>
          <FilterButton
            active={severityFilter === 'medium'}
            onClick={() => setSeverityFilter('medium')}
            color="medium"
          >
            Medium ({result.summary.medium})
          </FilterButton>
          <FilterButton
            active={severityFilter === 'low'}
            onClick={() => setSeverityFilter('low')}
            color="low"
          >
            Low ({result.summary.low})
          </FilterButton>
        </div>
      </div>

      {/* Findings List */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded overflow-hidden">
        <div className="p-4 border-b border-[var(--border)]">
          <h4 className="text-sm font-theme-data text-[var(--acid-green)]">
            {'>'} FINDINGS ({filteredFindings.length})
          </h4>
        </div>

        {filteredFindings.length === 0 ? (
          <div className="p-8 text-center text-[var(--text-muted)] font-theme-data text-sm">
            {severityFilter === 'all'
              ? 'No security issues found. Great job!'
              : `No ${severityFilter} severity findings.`}
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {filteredFindings.map((finding) => {
              const isExpanded = expandedFinding === finding.id;
              const config = SEVERITY_CONFIG[finding.severity];

              return (
                <div key={finding.id} className={`${config.bgColor} border-l-4`}>
                  <button
                    onClick={() => setExpandedFinding(isExpanded ? null : finding.id)}
                    className="w-full p-4 text-left"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span
                            className={`px-2 py-0.5 text-xs font-theme-data rounded border ${config.bgColor} ${config.color}`}
                          >
                            {config.label.toUpperCase()}
                          </span>
                          <span className="text-xs text-[var(--text-muted)]">{finding.id}</span>
                          {finding.cwe_id && (
                            <span className="text-xs text-purple-400">{finding.cwe_id}</span>
                          )}
                        </div>
                        <h5 className="font-theme-data text-sm text-[var(--text)]">
                          {finding.title}
                        </h5>
                        <p className="text-xs text-[var(--text-muted)] mt-1">
                          {finding.file_path}:{finding.line_number}
                        </p>
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="text-right">
                          <div className="text-xs text-[var(--text-muted)]">Confidence</div>
                          <div
                            className={`text-sm font-theme-data ${
                              finding.confidence >= 0.9
                                ? 'text-green-400'
                                : finding.confidence >= 0.7
                                  ? 'text-yellow-400'
                                  : 'text-red-400'
                            }`}
                          >
                            {Math.round(finding.confidence * 100)}%
                          </div>
                        </div>
                        <span className="text-[var(--text-muted)]">
                          {isExpanded ? '[-]' : '[+]'}
                        </span>
                      </div>
                    </div>
                  </button>

                  {isExpanded && (
                    <div className="px-4 pb-4 space-y-3 border-t border-[var(--border)]/30 pt-3">
                      <div>
                        <span className="text-xs text-[var(--text-muted)] block mb-1">
                          Description
                        </span>
                        <p className="text-sm">{finding.description}</p>
                      </div>

                      {finding.code_snippet && (
                        <div>
                          <span className="text-xs text-[var(--text-muted)] block mb-1">Code</span>
                          <pre className="p-3 bg-[var(--bg)] rounded font-theme-data text-xs overflow-x-auto">
                            <code>{finding.code_snippet}</code>
                          </pre>
                        </div>
                      )}

                      {finding.recommendation && (
                        <div className="p-3 bg-green-500/10 border border-green-500/30 rounded">
                          <span className="text-xs text-green-400 block mb-1">Recommendation</span>
                          <p className="text-sm text-green-300">{finding.recommendation}</p>
                        </div>
                      )}

                      <div className="flex gap-2 pt-2">
                        <button className="px-3 py-1 text-xs font-theme-data bg-[var(--bg)] border border-[var(--border)] rounded hover:border-[var(--acid-green)]/30 transition-colors">
                          View File
                        </button>
                        <button className="px-3 py-1 text-xs font-theme-data bg-[var(--bg)] border border-[var(--border)] rounded hover:border-[var(--acid-green)]/30 transition-colors">
                          Mark False Positive
                        </button>
                        <button className="px-3 py-1 text-xs font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 rounded hover:bg-[var(--acid-green)]/20 transition-colors">
                          Generate Fix
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

interface StatCardProps {
  label: string;
  value: string | number;
  color: string;
  pulse?: boolean;
  small?: boolean;
}

function StatCard({ label, value, color, pulse, small }: StatCardProps) {
  return (
    <div className="text-center">
      <div
        className={`${small ? 'text-lg' : 'text-2xl'} font-theme-data ${color} ${pulse ? 'animate-pulse' : ''}`}
      >
        {value}
      </div>
      <div className="text-xs text-[var(--text-muted)]">{label}</div>
    </div>
  );
}

interface FilterButtonProps {
  active: boolean;
  onClick: () => void;
  color: 'default' | 'critical' | 'high' | 'medium' | 'low';
  children: React.ReactNode;
}

function FilterButton({ active, onClick, color, children }: FilterButtonProps) {
  const colorClasses: Record<string, string> = {
    default: active
      ? 'bg-[var(--acid-green)]/20 border-[var(--acid-green)] text-[var(--acid-green)]'
      : 'border-[var(--border)] text-[var(--text-muted)]',
    critical: active
      ? 'bg-red-500/20 border-red-500 text-red-400'
      : 'border-[var(--border)] text-[var(--text-muted)]',
    high: active
      ? 'bg-orange-500/20 border-orange-500 text-orange-400'
      : 'border-[var(--border)] text-[var(--text-muted)]',
    medium: active
      ? 'bg-yellow-500/20 border-yellow-500 text-yellow-400'
      : 'border-[var(--border)] text-[var(--text-muted)]',
    low: active
      ? 'bg-blue-500/20 border-blue-500 text-blue-400'
      : 'border-[var(--border)] text-[var(--text-muted)]',
  };

  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 text-xs font-theme-data border rounded transition-colors ${colorClasses[color]} hover:opacity-80`}
    >
      {children}
    </button>
  );
}

export default FindingsSummary;
