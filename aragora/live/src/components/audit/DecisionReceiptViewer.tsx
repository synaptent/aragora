'use client';

import { useState } from 'react';

export interface ReceiptFinding {
  id: string;
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  category: string;
  title: string;
  description: string;
  mitigation?: string;
  source: string;
  verified: boolean;
}

export interface ReceiptDissent {
  agent: string;
  type: string;
  severity: number;
  reasons: string[];
  alternative?: string;
}

export interface ReceiptVerification {
  claim: string;
  verified: boolean;
  method: string;
  proof_hash?: string;
}

export interface DecisionReceipt {
  receipt_id: string;
  gauntlet_id: string;
  timestamp: string;
  input_summary: string;
  input_type: string;
  verdict: string;
  confidence: number;
  risk_level: string;
  findings: ReceiptFinding[];
  mitigations: string[];
  dissenting_views: ReceiptDissent[];
  unresolved_tensions: string[];
  verified_claims: ReceiptVerification[];
  unverified_claims: ReceiptVerification[];
  agents_involved: string[];
  rounds_completed: number;
  duration_seconds: number;
  checksum: string;
}

export interface DecisionReceiptViewerProps {
  receipt: DecisionReceipt;
  onVerify?: () => Promise<boolean>;
  onExportPdf?: () => void;
  onViewAuditTrail?: () => void;
  className?: string;
}

const SEVERITY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  CRITICAL: { bg: 'bg-red-900/40', text: 'text-red-400', border: 'border-red-800/50' },
  HIGH: { bg: 'bg-orange-900/30', text: 'text-orange-400', border: 'border-orange-800/50' },
  MEDIUM: { bg: 'bg-yellow-900/30', text: 'text-yellow-400', border: 'border-yellow-800/50' },
  LOW: { bg: 'bg-blue-900/20', text: 'text-blue-400', border: 'border-blue-800/50' },
};

const VERDICT_CONFIG: Record<string, { bg: string; text: string; icon: string }> = {
  approved: { bg: 'bg-green-900/30', text: 'text-green-400', icon: '[+]' },
  rejected: { bg: 'bg-red-900/30', text: 'text-red-400', icon: '[X]' },
  conditional: { bg: 'bg-yellow-900/30', text: 'text-yellow-400', icon: '[?]' },
  needs_review: { bg: 'bg-orange-900/30', text: 'text-orange-400', icon: '[!]' },
};

const RISK_COLORS: Record<string, string> = {
  low: 'text-green-400',
  medium: 'text-yellow-400',
  high: 'text-orange-400',
  critical: 'text-red-400',
};

/**
 * DecisionReceiptViewer - Displays a cryptographically-signed decision receipt.
 *
 * Shows verdict, findings, dissenting views, verified claims, and provides
 * integrity verification for compliance and audit purposes.
 */
export function DecisionReceiptViewer({
  receipt,
  onVerify,
  onExportPdf,
  onViewAuditTrail,
  className = '',
}: DecisionReceiptViewerProps) {
  const [activeTab, setActiveTab] = useState<'findings' | 'dissent' | 'claims'>('findings');
  const [verificationStatus, setVerificationStatus] = useState<
    'idle' | 'verifying' | 'valid' | 'invalid'
  >('idle');
  const [expandedFinding, setExpandedFinding] = useState<string | null>(null);

  const verdictConfig =
    VERDICT_CONFIG[receipt.verdict.toLowerCase()] || VERDICT_CONFIG.needs_review;
  const riskColor = RISK_COLORS[receipt.risk_level.toLowerCase()] || 'text-text-muted';

  const handleVerify = async () => {
    if (!onVerify) return;
    setVerificationStatus('verifying');
    try {
      const isValid = await onVerify();
      setVerificationStatus(isValid ? 'valid' : 'invalid');
    } catch {
      setVerificationStatus('invalid');
    }
  };

  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs.toFixed(0)}s`;
  };

  const findingsBySeverity = {
    CRITICAL: receipt.findings.filter((f) => f.severity === 'CRITICAL'),
    HIGH: receipt.findings.filter((f) => f.severity === 'HIGH'),
    MEDIUM: receipt.findings.filter((f) => f.severity === 'MEDIUM'),
    LOW: receipt.findings.filter((f) => f.severity === 'LOW'),
  };

  return (
    <div className={`bg-bg border border-border rounded-lg overflow-hidden ${className}`}>
      {/* Receipt Header - The "official document" look */}
      <div className="bg-surface/50 p-6 border-b border-border">
        <div className="flex items-start justify-between mb-4">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-[var(--accent)] font-theme-data text-sm">
                {verdictConfig.icon}
              </span>
              <h2 className="font-theme-data text-lg font-bold text-text">DECISION RECEIPT</h2>
            </div>
            <div className="text-xs font-theme-data text-text-muted">
              Receipt ID: <code className="text-[var(--acid-cyan)]">{receipt.receipt_id}</code>
            </div>
          </div>

          {/* Integrity Badge */}
          <div className="text-right">
            <div className="flex items-center gap-2 justify-end mb-1">
              {verificationStatus === 'idle' && onVerify && (
                <button
                  onClick={handleVerify}
                  className="px-3 py-1 text-xs font-theme-data bg-surface border border-border rounded hover:border-[var(--accent)] transition-colors"
                >
                  Verify Integrity
                </button>
              )}
              {verificationStatus === 'verifying' && (
                <span className="px-3 py-1 text-xs font-theme-data bg-surface border border-border rounded animate-pulse">
                  Verifying...
                </span>
              )}
              {verificationStatus === 'valid' && (
                <span className="px-3 py-1 text-xs font-theme-data bg-green-900/30 text-green-400 border border-green-800/30 rounded">
                  [+] VERIFIED
                </span>
              )}
              {verificationStatus === 'invalid' && (
                <span className="px-3 py-1 text-xs font-theme-data bg-red-900/30 text-red-400 border border-red-800/30 rounded">
                  [X] INVALID
                </span>
              )}
            </div>
            <div className="text-xs font-theme-data text-text-muted">
              Checksum: <code className="text-[var(--acid-cyan)]">{receipt.checksum}</code>
            </div>
          </div>
        </div>

        {/* Verdict Display */}
        <div className={`p-4 rounded-lg ${verdictConfig.bg} mb-4`}>
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs font-theme-data text-text-muted mb-1">VERDICT</div>
              <div className={`text-2xl font-theme-data font-bold ${verdictConfig.text}`}>
                {receipt.verdict.toUpperCase()}
              </div>
            </div>
            <div className="text-right">
              <div className="text-xs font-theme-data text-text-muted mb-1">CONFIDENCE</div>
              <div className="text-2xl font-theme-data font-bold text-[var(--acid-cyan)]">
                {(receipt.confidence * 100).toFixed(0)}%
              </div>
            </div>
            <div className="text-right">
              <div className="text-xs font-theme-data text-text-muted mb-1">RISK LEVEL</div>
              <div className={`text-2xl font-theme-data font-bold ${riskColor}`}>
                {receipt.risk_level.toUpperCase()}
              </div>
            </div>
          </div>
        </div>

        {/* Meta Information */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-theme-data">
          <div>
            <span className="text-text-muted">Input Type:</span>
            <div className="text-text">{receipt.input_type}</div>
          </div>
          <div>
            <span className="text-text-muted">Duration:</span>
            <div className="text-text">{formatDuration(receipt.duration_seconds)}</div>
          </div>
          <div>
            <span className="text-text-muted">Agents:</span>
            <div className="text-text">{receipt.agents_involved.length} involved</div>
          </div>
          <div>
            <span className="text-text-muted">Rounds:</span>
            <div className="text-text">{receipt.rounds_completed} completed</div>
          </div>
        </div>
      </div>

      {/* Input Summary */}
      <div className="p-4 border-b border-border">
        <div className="text-xs font-theme-data text-text-muted mb-2">INPUT SUMMARY</div>
        <p className="text-sm text-text">{receipt.input_summary}</p>
      </div>

      {/* Tabs */}
      <div className="border-b border-border">
        <div className="flex">
          <button
            onClick={() => setActiveTab('findings')}
            className={`flex-1 px-4 py-3 text-sm font-theme-data border-b-2 transition-colors ${
              activeTab === 'findings'
                ? 'border-[var(--accent)] text-[var(--accent)] bg-surface/30'
                : 'border-transparent text-text-muted hover:text-text'
            }`}
          >
            Findings ({receipt.findings.length})
          </button>
          <button
            onClick={() => setActiveTab('dissent')}
            className={`flex-1 px-4 py-3 text-sm font-theme-data border-b-2 transition-colors ${
              activeTab === 'dissent'
                ? 'border-[var(--accent)] text-[var(--accent)] bg-surface/30'
                : 'border-transparent text-text-muted hover:text-text'
            }`}
          >
            Dissent ({receipt.dissenting_views.length})
          </button>
          <button
            onClick={() => setActiveTab('claims')}
            className={`flex-1 px-4 py-3 text-sm font-theme-data border-b-2 transition-colors ${
              activeTab === 'claims'
                ? 'border-[var(--accent)] text-[var(--accent)] bg-surface/30'
                : 'border-transparent text-text-muted hover:text-text'
            }`}
          >
            Claims ({receipt.verified_claims.length + receipt.unverified_claims.length})
          </button>
        </div>
      </div>

      {/* Tab Content */}
      <div className="p-4 max-h-80 overflow-y-auto">
        {/* Findings Tab */}
        {activeTab === 'findings' && (
          <div className="space-y-3">
            {receipt.findings.length === 0 ? (
              <div className="text-center py-6 text-text-muted font-theme-data">
                No findings recorded
              </div>
            ) : (
              <>
                {/* Severity summary */}
                <div className="flex gap-2 mb-4">
                  {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const).map((sev) => (
                    <span
                      key={sev}
                      className={`px-2 py-1 text-xs font-theme-data rounded ${SEVERITY_COLORS[sev].bg} ${SEVERITY_COLORS[sev].text}`}
                    >
                      {sev}: {findingsBySeverity[sev].length}
                    </span>
                  ))}
                </div>

                {/* Findings list */}
                {receipt.findings.map((finding) => {
                  const colors = SEVERITY_COLORS[finding.severity];
                  const isExpanded = expandedFinding === finding.id;

                  return (
                    <div
                      key={finding.id}
                      onClick={() => setExpandedFinding(isExpanded ? null : finding.id)}
                      className={`p-3 rounded border cursor-pointer transition-all ${colors.bg} ${colors.border} ${
                        isExpanded ? 'ring-1 ring-acid-green' : ''
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-1">
                            <span
                              className={`px-2 py-0.5 text-xs font-theme-data uppercase rounded ${colors.text}`}
                            >
                              {finding.severity}
                            </span>
                            <span className="text-xs text-text-muted font-theme-data">
                              {finding.category}
                            </span>
                            {finding.verified && (
                              <span className="text-xs text-green-400 font-theme-data">
                                [VERIFIED]
                              </span>
                            )}
                          </div>
                          <h4 className="font-theme-data font-bold text-text">{finding.title}</h4>
                        </div>
                      </div>

                      {isExpanded && (
                        <div className="mt-3 pt-3 border-t border-border/30 space-y-2">
                          <p className="text-sm text-text-muted">{finding.description}</p>
                          {finding.mitigation && (
                            <div>
                              <span className="text-xs font-theme-data text-[var(--accent)]">
                                Mitigation:
                              </span>
                              <p className="text-sm text-text ml-2">{finding.mitigation}</p>
                            </div>
                          )}
                          <div className="text-xs text-text-muted font-theme-data">
                            Source: {finding.source}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </>
            )}
          </div>
        )}

        {/* Dissent Tab */}
        {activeTab === 'dissent' && (
          <div className="space-y-3">
            {receipt.dissenting_views.length === 0 ? (
              <div className="text-center py-6 text-text-muted font-theme-data">
                No dissenting views recorded - consensus achieved
              </div>
            ) : (
              receipt.dissenting_views.map((dissent, idx) => (
                <div key={idx} className="p-3 rounded border border-orange-800/30 bg-orange-900/20">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-theme-data font-bold text-orange-400">
                      {dissent.agent}
                    </span>
                    <span className="text-xs font-theme-data text-text-muted">
                      Severity: {(dissent.severity * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="text-xs font-theme-data text-text-muted mb-2">
                    Type: {dissent.type}
                  </div>
                  <ul className="text-sm text-text space-y-1">
                    {dissent.reasons.map((reason, i) => (
                      <li key={i} className="flex items-start gap-2">
                        <span className="text-orange-400">-</span>
                        <span>{reason}</span>
                      </li>
                    ))}
                  </ul>
                  {dissent.alternative && (
                    <div className="mt-2 pt-2 border-t border-border/30">
                      <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
                        Alternative proposed:
                      </span>
                      <p className="text-sm text-text mt-1">{dissent.alternative}</p>
                    </div>
                  )}
                </div>
              ))
            )}

            {/* Unresolved Tensions */}
            {receipt.unresolved_tensions.length > 0 && (
              <div className="mt-4 pt-4 border-t border-border">
                <div className="text-xs font-theme-data text-text-muted mb-2">
                  UNRESOLVED TENSIONS
                </div>
                <ul className="space-y-2">
                  {receipt.unresolved_tensions.map((tension, idx) => (
                    <li key={idx} className="text-sm text-yellow-400 flex items-start gap-2">
                      <span>[!]</span>
                      <span>{tension}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Claims Tab */}
        {activeTab === 'claims' && (
          <div className="space-y-4">
            {/* Verified Claims */}
            <div>
              <div className="text-xs font-theme-data text-green-400 mb-2">
                VERIFIED CLAIMS ({receipt.verified_claims.length})
              </div>
              {receipt.verified_claims.length === 0 ? (
                <div className="text-xs text-text-muted font-theme-data">No verified claims</div>
              ) : (
                <div className="space-y-2">
                  {receipt.verified_claims.map((claim, idx) => (
                    <div
                      key={idx}
                      className="p-2 rounded border border-green-800/30 bg-green-900/20"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-sm text-text flex-1">{claim.claim}</p>
                        <span className="text-xs font-theme-data text-green-400 flex-shrink-0">
                          {claim.verified ? '[+]' : '[-]'}
                        </span>
                      </div>
                      <div className="flex items-center gap-4 mt-1 text-xs text-text-muted font-theme-data">
                        <span>Method: {claim.method}</span>
                        {claim.proof_hash && (
                          <span>
                            Proof:{' '}
                            <code className="text-[var(--acid-cyan)]">
                              {claim.proof_hash.slice(0, 12)}...
                            </code>
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Unverified Claims */}
            <div>
              <div className="text-xs font-theme-data text-yellow-400 mb-2">
                UNVERIFIED CLAIMS ({receipt.unverified_claims.length})
              </div>
              {receipt.unverified_claims.length === 0 ? (
                <div className="text-xs text-text-muted font-theme-data">All claims verified</div>
              ) : (
                <div className="space-y-2">
                  {receipt.unverified_claims.map((claim, idx) => (
                    <div
                      key={idx}
                      className="p-2 rounded border border-yellow-800/30 bg-yellow-900/20"
                    >
                      <p className="text-sm text-text">{claim.claim}</p>
                      <div className="text-xs text-text-muted font-theme-data mt-1">
                        Method attempted: {claim.method}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Footer Actions */}
      <div className="p-4 border-t border-border bg-surface/30 flex items-center justify-between">
        <div className="text-xs font-theme-data text-text-muted">
          Generated: {new Date(receipt.timestamp).toLocaleString()}
        </div>
        <div className="flex gap-2">
          {onViewAuditTrail && (
            <button
              onClick={onViewAuditTrail}
              className="px-3 py-1.5 text-xs font-theme-data bg-surface border border-border rounded hover:border-[var(--acid-cyan)] hover:text-[var(--acid-cyan)] transition-colors"
            >
              View Audit Trail
            </button>
          )}
          {onExportPdf && (
            <button
              onClick={onExportPdf}
              className="px-3 py-1.5 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/30 rounded hover:bg-[var(--accent)]/30 transition-colors"
            >
              Export PDF
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default DecisionReceiptViewer;
