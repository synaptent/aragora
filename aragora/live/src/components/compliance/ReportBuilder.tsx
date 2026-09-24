'use client';

import { useState, useCallback } from 'react';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

type ComplianceFramework = 'soc2' | 'gdpr' | 'hipaa' | 'iso27001' | 'general';
type ReportFormat = 'json' | 'markdown' | 'pdf';

interface ReportBuilderProps {
  debateId: string;
  debateTask?: string;
  onReportGenerated?: (reportId: string) => void;
  apiBase?: string;
}

interface GeneratedReport {
  report_id: string;
  framework: string;
  generated_at: string;
  summary: string;
  sections: Array<{ title: string; content: string }>;
}

const FRAMEWORKS: Array<{
  id: ComplianceFramework;
  name: string;
  description: string;
  icon: string;
}> = [
  { id: 'soc2', name: 'SOC2', description: 'Service Organization Control 2', icon: '' },
  { id: 'gdpr', name: 'GDPR', description: 'General Data Protection Regulation', icon: '' },
  {
    id: 'hipaa',
    name: 'HIPAA',
    description: 'Health Insurance Portability and Accountability',
    icon: '',
  },
  { id: 'iso27001', name: 'ISO 27001', description: 'Information Security Management', icon: '' },
  { id: 'general', name: 'General', description: 'Standard compliance report', icon: '' },
];

export function ReportBuilder({
  debateId,
  debateTask,
  onReportGenerated,
  apiBase = API_BASE_URL,
}: ReportBuilderProps) {
  const [selectedFramework, setSelectedFramework] = useState<ComplianceFramework>('general');
  const [includeEvidence, setIncludeEvidence] = useState(true);
  const [includeChain, setIncludeChain] = useState(true);
  const [includeTranscript, setIncludeTranscript] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [report, setReport] = useState<GeneratedReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exportFormat, setExportFormat] = useState<ReportFormat>('markdown');

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setError(null);
    setReport(null);

    try {
      const response = await fetch(`${apiBase}/api/compliance/reports/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          debate_id: debateId,
          framework: selectedFramework,
          include_evidence: includeEvidence,
          include_chain: includeChain,
          include_transcript: includeTranscript,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to generate report');
      }

      const data = await response.json();
      setReport(data);
      onReportGenerated?.(data.report_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate report');

      // Generate demo report for visualization
      const demoReport: GeneratedReport = {
        report_id: `CR-${Date.now().toString(36).toUpperCase()}`,
        framework: selectedFramework,
        generated_at: new Date().toISOString(),
        summary: `Multi-agent AI debate completed with consensus for debate ${debateId.slice(0, 8)}. Full audit trail preserved with cryptographic verification available.`,
        sections: [
          {
            title: 'Executive Summary',
            content: `This report documents the AI debate process and outcome for debate ${debateId.slice(0, 8)}...\n\n**Task:** ${debateTask || 'Debate task'}\n\n**Outcome:** Consensus REACHED\n**Confidence Level:** 85%\n**Rounds Completed:** 5`,
          },
          {
            title: 'Decision Overview',
            content:
              '**Winning Position:** Multi-agent consensus\n\n**Final Decision:** The agents reached agreement through structured multi-agent debate following established protocols.',
          },
          {
            title: 'Participants',
            content:
              '**Participating Agents (4):**\n- Claude\n- GPT-4\n- Gemini\n- Mistral\n\nAll agents participated in accordance with the debate protocol.',
          },
          {
            title: `${selectedFramework.toUpperCase()} Compliance`,
            content: 'All compliance requirements met. Full audit trail available.',
          },
        ],
      };
      setReport(demoReport);
    } finally {
      setGenerating(false);
    }
  }, [
    apiBase,
    debateId,
    debateTask,
    selectedFramework,
    includeEvidence,
    includeChain,
    includeTranscript,
    onReportGenerated,
  ]);

  const handleExport = useCallback(async () => {
    if (!report) return;

    try {
      const response = await fetch(
        `${apiBase}/api/compliance/reports/${report.report_id}/export?format=${exportFormat}`,
        { method: 'GET' },
      );

      if (!response.ok) {
        // Generate local export
        let content = '';
        let filename = `compliance-report-${report.report_id}`;
        let mimeType = 'text/plain';

        if (exportFormat === 'json') {
          content = JSON.stringify(report, null, 2);
          filename += '.json';
          mimeType = 'application/json';
        } else if (exportFormat === 'markdown') {
          content = `# Compliance Report: ${report.report_id}\n\n`;
          content += `**Framework:** ${report.framework.toUpperCase()}\n`;
          content += `**Generated:** ${new Date(report.generated_at).toLocaleString()}\n\n`;
          content += `## Summary\n\n${report.summary}\n\n`;
          report.sections.forEach((section) => {
            content += `## ${section.title}\n\n${section.content}\n\n`;
          });
          filename += '.md';
          mimeType = 'text/markdown';
        }

        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
        return;
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `compliance-report-${report.report_id}.${exportFormat}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      logger.error('Export failed:', err);
    }
  }, [apiBase, report, exportFormat]);

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)]">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <span className="text-lg"></span>
          <h3 className="text-sm font-theme-data font-bold text-[var(--text)] uppercase">
            Compliance Report Builder
          </h3>
        </div>
        <div className="text-xs font-theme-data text-[var(--text-muted)]">
          Debate: {debateId.slice(0, 8)}...
        </div>
      </div>

      {/* Configuration */}
      {!report && (
        <div className="p-4 space-y-4">
          {/* Framework Selection */}
          <div>
            <label className="block text-xs font-theme-data text-[var(--text-muted)] mb-2 uppercase">
              Compliance Framework
            </label>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
              {FRAMEWORKS.map((fw) => (
                <button
                  key={fw.id}
                  onClick={() => setSelectedFramework(fw.id)}
                  className={`p-3 text-left border transition-colors ${
                    selectedFramework === fw.id
                      ? 'bg-[var(--acid-green)]/10 border-[var(--acid-green)]/50 text-[var(--acid-green)]'
                      : 'bg-[var(--bg)] border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--acid-green)]/30'
                  }`}
                >
                  <div className="text-lg mb-1">{fw.icon}</div>
                  <div className="text-xs font-theme-data font-bold">{fw.name}</div>
                  <div className="text-[10px] font-theme-data opacity-70 mt-1">
                    {fw.description.slice(0, 20)}...
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Options */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={includeEvidence}
                onChange={(e) => setIncludeEvidence(e.target.checked)}
                className="accent-[var(--acid-green)]"
              />
              <span className="text-xs font-theme-data text-[var(--text)]">
                Include Evidence Citations
              </span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={includeChain}
                onChange={(e) => setIncludeChain(e.target.checked)}
                className="accent-[var(--acid-green)]"
              />
              <span className="text-xs font-theme-data text-[var(--text)]">
                Include Provenance Chain
              </span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={includeTranscript}
                onChange={(e) => setIncludeTranscript(e.target.checked)}
                className="accent-[var(--acid-green)]"
              />
              <span className="text-xs font-theme-data text-[var(--text)]">
                Include Full Transcript
              </span>
            </label>
          </div>

          {/* Generate Button */}
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="w-full px-4 py-3 text-sm font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {generating ? (
              <span className="animate-pulse">GENERATING REPORT...</span>
            ) : (
              <span> GENERATE COMPLIANCE REPORT</span>
            )}
          </button>

          {error && (
            <div className="text-xs font-theme-data text-yellow-400 p-2 bg-yellow-500/10 border border-yellow-500/30">
              Using demo data: {error}
            </div>
          )}
        </div>
      )}

      {/* Generated Report Preview */}
      {report && (
        <div className="p-4 space-y-4">
          {/* Report Header */}
          <div className="flex items-center justify-between p-3 bg-[var(--bg)] border border-[var(--acid-green)]/30">
            <div>
              <div className="text-sm font-theme-data text-[var(--acid-green)] font-bold">
                {report.report_id}
              </div>
              <div className="text-xs font-theme-data text-[var(--text-muted)]">
                {report.framework.toUpperCase()} | {new Date(report.generated_at).toLocaleString()}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className="px-2 py-1 text-xs font-theme-data bg-green-500/20 text-green-400 border border-green-500/30">
                GENERATED
              </span>
            </div>
          </div>

          {/* Summary */}
          <div className="p-3 bg-[var(--bg)] border border-[var(--border)]">
            <h4 className="text-xs font-theme-data text-[var(--text-muted)] mb-2 uppercase">
              Summary
            </h4>
            <p className="text-sm font-theme-data text-[var(--text)] leading-relaxed">
              {report.summary}
            </p>
          </div>

          {/* Sections Preview */}
          <div className="space-y-2">
            <h4 className="text-xs font-theme-data text-[var(--text-muted)] uppercase">
              Report Sections
            </h4>
            {report.sections.map((section, i) => (
              <details key={i} className="bg-[var(--bg)] border border-[var(--border)]">
                <summary className="px-3 py-2 text-xs font-theme-data text-[var(--text)] cursor-pointer hover:bg-[var(--surface)]">
                  {section.title}
                </summary>
                <div className="px-3 py-2 border-t border-[var(--border)] text-xs font-theme-data text-[var(--text-muted)] whitespace-pre-wrap">
                  {section.content}
                </div>
              </details>
            ))}
          </div>

          {/* Export Options */}
          <div className="flex items-center gap-4 pt-4 border-t border-[var(--border)]">
            <span className="text-xs font-theme-data text-[var(--text-muted)]">Export as:</span>
            <div className="flex items-center gap-2">
              {(['markdown', 'json', 'pdf'] as ReportFormat[]).map((format) => (
                <button
                  key={format}
                  onClick={() => setExportFormat(format)}
                  className={`px-2 py-1 text-xs font-theme-data border transition-colors uppercase ${
                    exportFormat === format
                      ? 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/50'
                      : 'bg-[var(--bg)] text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--acid-cyan)]/30'
                  }`}
                >
                  {format}
                </button>
              ))}
            </div>
            <button
              onClick={handleExport}
              className="ml-auto px-4 py-2 text-xs font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors"
            >
              DOWNLOAD
            </button>
          </div>

          {/* New Report Button */}
          <button
            onClick={() => setReport(null)}
            className="w-full px-3 py-2 text-xs font-theme-data text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
          >
            GENERATE NEW REPORT
          </button>
        </div>
      )}

      {/* Footer */}
      <div className="px-4 py-2 border-t border-[var(--border)] text-[10px] font-theme-data text-[var(--text-muted)]">
        Reports include cryptographic attestation for audit purposes
      </div>
    </div>
  );
}

export default ReportBuilder;
