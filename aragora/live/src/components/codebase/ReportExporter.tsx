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

interface ReportExporterProps {
  result: ScanResult;
}

type ExportFormat = 'json' | 'csv' | 'sarif' | 'markdown';

const EXPORT_FORMATS: Array<{ id: ExportFormat; name: string; description: string; icon: string }> =
  [
    { id: 'json', name: 'JSON', description: 'Full scan data in JSON format', icon: '{ }' },
    { id: 'csv', name: 'CSV', description: 'Spreadsheet-compatible format', icon: '=' },
    {
      id: 'sarif',
      name: 'SARIF',
      description: 'Standard format for code scanning tools',
      icon: '#',
    },
    { id: 'markdown', name: 'Markdown', description: 'Human-readable report', icon: 'M' },
  ];

export function ReportExporter({ result }: ReportExporterProps) {
  const [exporting, setExporting] = useState<ExportFormat | null>(null);
  const [copied, setCopied] = useState(false);

  const generateJSON = (): string => {
    return JSON.stringify(result, null, 2);
  };

  const generateCSV = (): string => {
    const headers = [
      'ID',
      'Severity',
      'Title',
      'Category',
      'File',
      'Line',
      'CWE',
      'Confidence',
      'Description',
    ];
    const rows = result.findings.map((f) => [
      f.id,
      f.severity,
      `"${f.title.replace(/"/g, '""')}"`,
      f.category,
      `"${f.file_path}"`,
      f.line_number.toString(),
      f.cwe_id || '',
      (f.confidence * 100).toFixed(0) + '%',
      `"${f.description.replace(/"/g, '""')}"`,
    ]);
    return [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
  };

  const generateSARIF = (): string => {
    const sarif = {
      $schema:
        'https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json',
      version: '2.1.0',
      runs: [
        {
          tool: {
            driver: {
              name: 'Aragora Security Scanner',
              version: '1.0.0',
              informationUri: 'https://aragora.ai',
              rules: result.findings.map((f) => ({
                id: f.id,
                name: f.title,
                shortDescription: { text: f.title },
                fullDescription: { text: f.description },
                defaultConfiguration: {
                  level:
                    f.severity === 'critical' || f.severity === 'high'
                      ? 'error'
                      : f.severity === 'medium'
                        ? 'warning'
                        : 'note',
                },
                properties: { category: f.category, cwe: f.cwe_id },
              })),
            },
          },
          results: result.findings.map((f) => ({
            ruleId: f.id,
            level:
              f.severity === 'critical' || f.severity === 'high'
                ? 'error'
                : f.severity === 'medium'
                  ? 'warning'
                  : 'note',
            message: { text: f.description },
            locations: [
              {
                physicalLocation: {
                  artifactLocation: { uri: f.file_path },
                  region: { startLine: f.line_number },
                },
              },
            ],
            properties: { confidence: f.confidence, recommendation: f.recommendation },
          })),
        },
      ],
    };
    return JSON.stringify(sarif, null, 2);
  };

  const generateMarkdown = (): string => {
    const lines: string[] = [];

    lines.push('# Security Scan Report');
    lines.push('');
    lines.push(`**Scan ID:** ${result.scan_id}`);
    lines.push(`**Repository:** ${result.repository}`);
    lines.push(`**Files Scanned:** ${result.files_scanned}`);
    if (result.lines_scanned) {
      lines.push(`**Lines Analyzed:** ${result.lines_scanned.toLocaleString()}`);
    }
    if (result.risk_score !== undefined) {
      lines.push(`**Risk Score:** ${result.risk_score.toFixed(0)}/100`);
    }
    lines.push('');

    lines.push('## Summary');
    lines.push('');
    lines.push('| Severity | Count |');
    lines.push('|----------|-------|');
    lines.push(`| Critical | ${result.summary.critical} |`);
    lines.push(`| High | ${result.summary.high} |`);
    lines.push(`| Medium | ${result.summary.medium} |`);
    lines.push(`| Low | ${result.summary.low} |`);
    if (result.summary.info !== undefined) {
      lines.push(`| Info | ${result.summary.info} |`);
    }
    lines.push('');

    if (result.findings.length > 0) {
      lines.push('## Findings');
      lines.push('');

      const severityOrder = ['critical', 'high', 'medium', 'low', 'info'];
      const sortedFindings = [...result.findings].sort(
        (a, b) => severityOrder.indexOf(a.severity) - severityOrder.indexOf(b.severity),
      );

      for (const finding of sortedFindings) {
        lines.push(`### ${finding.id}: ${finding.title}`);
        lines.push('');
        lines.push(`**Severity:** ${finding.severity.toUpperCase()}`);
        lines.push(`**Confidence:** ${Math.round(finding.confidence * 100)}%`);
        lines.push(`**Location:** \`${finding.file_path}:${finding.line_number}\``);
        if (finding.cwe_id) {
          lines.push(`**CWE:** ${finding.cwe_id}`);
        }
        lines.push('');
        lines.push(finding.description);
        lines.push('');

        if (finding.code_snippet) {
          lines.push('**Code:**');
          lines.push('```');
          lines.push(finding.code_snippet);
          lines.push('```');
          lines.push('');
        }

        if (finding.recommendation) {
          lines.push(`**Recommendation:** ${finding.recommendation}`);
          lines.push('');
        }

        lines.push('---');
        lines.push('');
      }
    }

    lines.push('');
    lines.push('*Generated by Aragora Security Scanner*');

    return lines.join('\n');
  };

  const exportReport = async (format: ExportFormat) => {
    setExporting(format);

    let content: string;
    let filename: string;
    let mimeType: string;

    switch (format) {
      case 'json':
        content = generateJSON();
        filename = `security-report-${result.scan_id}.json`;
        mimeType = 'application/json';
        break;
      case 'csv':
        content = generateCSV();
        filename = `security-report-${result.scan_id}.csv`;
        mimeType = 'text/csv';
        break;
      case 'sarif':
        content = generateSARIF();
        filename = `security-report-${result.scan_id}.sarif`;
        mimeType = 'application/json';
        break;
      case 'markdown':
        content = generateMarkdown();
        filename = `security-report-${result.scan_id}.md`;
        mimeType = 'text/markdown';
        break;
    }

    // Create download
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    setTimeout(() => setExporting(null), 500);
  };

  const copyToClipboard = async () => {
    const content = generateJSON();
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
      <div className="flex items-center justify-between mb-4">
        <h4 className="text-sm font-theme-data text-[var(--acid-green)]">{'>'} EXPORT REPORT</h4>
        <button
          onClick={copyToClipboard}
          className="px-3 py-1 text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--text)] border border-[var(--border)] rounded hover:border-[var(--acid-green)]/30 transition-colors"
        >
          {copied ? '✓ Copied!' : 'Copy JSON'}
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {EXPORT_FORMATS.map((format) => (
          <button
            key={format.id}
            onClick={() => exportReport(format.id)}
            disabled={exporting !== null}
            className={`p-3 text-left border rounded transition-colors ${
              exporting === format.id
                ? 'border-[var(--acid-green)] bg-[var(--acid-green)]/10'
                : 'border-[var(--border)] hover:border-[var(--acid-green)]/30'
            } ${exporting !== null && exporting !== format.id ? 'opacity-50' : ''}`}
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="w-6 h-6 flex items-center justify-center bg-[var(--bg)] rounded text-xs font-theme-data text-[var(--acid-cyan)]">
                {format.icon}
              </span>
              <span className="font-theme-data text-sm text-[var(--text)]">{format.name}</span>
            </div>
            <p className="text-xs text-[var(--text-muted)]">{format.description}</p>
          </button>
        ))}
      </div>

      {/* Quick Stats for Export */}
      <div className="mt-4 pt-4 border-t border-[var(--border)] grid grid-cols-3 gap-4 text-center">
        <div>
          <div className="text-sm font-theme-data text-[var(--text)]">{result.findings.length}</div>
          <div className="text-xs text-[var(--text-muted)]">Findings to Export</div>
        </div>
        <div>
          <div className="text-sm font-theme-data text-red-400">
            {result.summary.critical + result.summary.high}
          </div>
          <div className="text-xs text-[var(--text-muted)]">Critical/High</div>
        </div>
        <div>
          <div className="text-sm font-theme-data text-[var(--acid-cyan)]">
            {result.files_scanned}
          </div>
          <div className="text-xs text-[var(--text-muted)]">Files Scanned</div>
        </div>
      </div>
    </div>
  );
}

export default ReportExporter;
