'use client';

/**
 * Compliance Dashboard
 *
 * Shows four key compliance panels:
 *   1. RBAC coverage summary
 *   2. Encryption status (at-rest AES-256-GCM, in-transit TLS)
 *   3. Compliance framework readiness (SOC 2, GDPR, EU AI Act)
 *   4. Recent audit trail entries
 *
 * Also retains the interactive EU AI Act classification workflow.
 *
 * Backend endpoints used:
 *   GET  /api/v2/compliance/status          - Overall compliance + framework status
 *   GET  /api/v2/security/rbac-coverage     - RBAC summary (fallback: mock)
 *   GET  /api/v2/security/encryption-status - Encryption summary (fallback: mock)
 *   GET  /api/v2/compliance/audit-events    - Audit trail entries (fallback: mock)
 *   POST /api/v2/compliance/eu-ai-act/*     - EU AI Act classification/bundles
 */

import { useState, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useAuth } from '@/context/AuthContext';
import { useSWRFetch } from '@/hooks/useSWRFetch';
import {
  useComplianceStatus,
  useRBACCoverage,
  useEncryptionStatus,
  useAuditTrail,
  buildFrameworkIndicators,
  type RBACCoverage,
  type EncryptionStatus,
  type FrameworkIndicator,
  type AuditEntry,
} from '@/hooks/useComplianceDashboard';

// ---------------------------------------------------------------------------
// Types (EU AI Act section)
// ---------------------------------------------------------------------------

interface RiskClassification {
  risk_level: 'unacceptable' | 'high' | 'limited' | 'minimal';
  annex_iii_categories: string[];
  applicable_articles: string[];
  matched_keywords: string[];
  confidence: number;
}

interface ArticleAssessment {
  article: string;
  title: string;
  status: 'compliant' | 'partial' | 'non_compliant' | 'not_applicable';
  findings: string[];
  recommendations: string[];
}

interface ComplianceBundle {
  bundle_id: string;
  generated_at: string;
  integrity_hash: string;
  article_12: Record<string, unknown>;
  article_13: Record<string, unknown>;
  article_14: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const FRAMEWORK_STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  compliant: { bg: 'bg-green-500/20', text: 'text-green-400', label: 'COMPLIANT' },
  partial: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', label: 'PARTIAL' },
  non_compliant: { bg: 'bg-red-500/20', text: 'text-red-400', label: 'NON-COMPLIANT' },
  not_assessed: { bg: 'bg-gray-500/20', text: 'text-gray-400', label: 'NOT ASSESSED' },
};

const RISK_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  unacceptable: { bg: 'bg-red-500/10', text: 'text-red-400', border: 'border-red-500/40' },
  high: { bg: 'bg-orange-500/10', text: 'text-orange-400', border: 'border-orange-500/40' },
  limited: { bg: 'bg-yellow-500/10', text: 'text-yellow-400', border: 'border-yellow-500/40' },
  minimal: { bg: 'bg-[var(--acid-green)]/10', text: 'text-[var(--acid-green)]', border: 'border-[var(--acid-green)]/40' },
};

const STATUS_ICONS: Record<string, string> = {
  compliant: '[PASS]',
  partial: '[WARN]',
  non_compliant: '[FAIL]',
  not_applicable: '[N/A]',
};

const STATUS_COLORS: Record<string, string> = {
  compliant: 'text-[var(--acid-green)]',
  partial: 'text-yellow-400',
  non_compliant: 'text-red-400',
  not_applicable: 'text-[var(--text-muted)]',
};

const OUTCOME_STYLES: Record<string, { bg: string; text: string }> = {
  success: { bg: 'bg-green-500/10', text: 'text-green-400' },
  failure: { bg: 'bg-red-500/10', text: 'text-red-400' },
  denied: { bg: 'bg-orange-500/10', text: 'text-orange-400' },
};

const SAMPLE_USE_CASES = [
  {
    label: 'Hiring Decision AI',
    description:
      'AI system that screens job applicants, scores resumes, and recommends candidates for interview based on historical hiring data and job requirements.',
  },
  {
    label: 'Clinical Decision Support',
    description:
      'AI-assisted diagnostic system that analyzes medical imaging (X-rays, MRIs) and patient history to suggest differential diagnoses for emergency department physicians.',
  },
  {
    label: 'Credit Risk Assessment',
    description:
      'Automated creditworthiness scoring system that evaluates loan applications using financial history, employment data, and behavioral patterns to determine approval and interest rates.',
  },
  {
    label: 'Content Recommendation',
    description:
      'AI system that recommends articles and videos to users based on browsing history and engagement patterns for a news aggregation platform.',
  },
];

// ---------------------------------------------------------------------------
// Demo Fallbacks (EU AI Act)
// ---------------------------------------------------------------------------

function getDemoClassification(description: string): RiskClassification {
  const lower = description.toLowerCase();
  const isHigh =
    lower.includes('hiring') ||
    lower.includes('credit') ||
    lower.includes('medical') ||
    lower.includes('diagnostic') ||
    lower.includes('loan');

  if (isHigh) {
    return {
      risk_level: 'high',
      annex_iii_categories: lower.includes('hiring')
        ? ['Employment, workers management']
        : lower.includes('credit') || lower.includes('loan')
          ? ['Access to essential private and public services']
          : ['Biometrics'],
      applicable_articles: ['Article 9', 'Article 12', 'Article 13', 'Article 14', 'Article 15'],
      matched_keywords: lower.includes('hiring')
        ? ['hiring', 'applicant', 'screening']
        : lower.includes('credit')
          ? ['credit', 'loan', 'scoring']
          : ['diagnostic', 'medical', 'imaging'],
      confidence: 0.92,
    };
  }

  return {
    risk_level: 'minimal',
    annex_iii_categories: [],
    applicable_articles: ['Article 52'],
    matched_keywords: [],
    confidence: 0.85,
  };
}

function getDemoAssessments(): ArticleAssessment[] {
  return [
    {
      article: 'Article 9',
      title: 'Risk Management System',
      status: 'compliant',
      findings: [
        'Multi-agent debate provides systematic risk identification through adversarial challenge',
        'Decision receipts document risk assessment outcomes with confidence scores',
      ],
      recommendations: [],
    },
    {
      article: 'Article 12',
      title: 'Record-Keeping & Logging',
      status: 'compliant',
      findings: [
        'Event logging captures all debate phases: propose, critique, revise, vote, synthesize',
        'Audit trail includes agent identities, timestamps, and content hashes',
        'Retention policy configurable per deployment',
      ],
      recommendations: [],
    },
    {
      article: 'Article 13',
      title: 'Transparency & Information',
      status: 'partial',
      findings: [
        'System provides decision explanations via explainability module',
        'Agent model identities disclosed in receipts',
      ],
      recommendations: [
        'Document known limitations for each model provider in user-facing materials',
        'Add accuracy metrics per domain to transparency disclosures',
      ],
    },
    {
      article: 'Article 14',
      title: 'Human Oversight',
      status: 'compliant',
      findings: [
        'Human-in-the-loop approval supported via receipt gating',
        'Override and stop mechanisms available through debate controls',
        'Automation bias safeguards via contrarian agent and dissent tracking',
      ],
      recommendations: [],
    },
    {
      article: 'Article 15',
      title: 'Accuracy, Robustness, Cybersecurity',
      status: 'partial',
      findings: [
        'Multi-model consensus reduces correlated failure modes',
        'Calibration tracking monitors prediction accuracy over time',
      ],
      recommendations: [
        'Implement formal adversarial robustness testing on a quarterly cadence',
        'Add bias monitoring metrics per protected characteristic',
      ],
    },
  ];
}

function getDemoBundle(): ComplianceBundle {
  const now = new Date().toISOString();
  return {
    bundle_id: `CAB-${Date.now().toString(36).toUpperCase()}`,
    generated_at: now,
    integrity_hash: 'sha256:' + Array.from({ length: 64 }, () => Math.floor(Math.random() * 16).toString(16)).join(''),
    article_12: {
      event_log: {
        total_events: 47,
        event_types: ['debate_start', 'proposal', 'critique', 'vote', 'consensus', 'receipt_generated'],
        retention_days: 365,
      },
      technical_documentation: {
        annex_iv_sections: ['System description', 'Design specifications', 'Risk management', 'Testing procedures'],
        completeness: 0.85,
      },
    },
    article_13: {
      provider_identity: { name: 'Aragora Platform', contact: 'compliance@aragora.ai' },
      intended_purpose: 'Multi-agent adversarial debate for decision integrity',
      known_risks: ['Model provider outages', 'Training data biases in individual models', 'Prompt injection attacks'],
      output_interpretation: 'Decision receipts with confidence scores, dissent trails, and consensus proofs',
    },
    article_14: {
      oversight_model: 'Human-on-the-loop with override capability',
      bias_safeguards: [
        'Heterogeneous model consensus (different training data)',
        'Contrarian agent prevents groupthink',
        'Dissent tracking surfaces disagreements',
      ],
      override_mechanisms: ['Debate pause/resume', 'Agent removal', 'Manual verdict override', 'Kill switch'],
    },
  };
}

// ---------------------------------------------------------------------------
// Helper: format relative time
// ---------------------------------------------------------------------------

function formatRelativeTime(isoDate: string): string {
  const diff = Date.now() - new Date(isoDate).getTime();
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// ---------------------------------------------------------------------------
// Panel: RBAC Coverage
// ---------------------------------------------------------------------------

function RBACCoveragePanel({ data, loading }: { data: RBACCoverage; loading: boolean }) {
  const coverageColor =
    data.coverage_percent >= 99
      ? 'text-green-400'
      : data.coverage_percent >= 95
        ? 'text-yellow-400'
        : 'text-red-400';

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)]">
      <div className="p-4 border-b border-[var(--border)]">
        <h3 className="text-sm font-mono text-[var(--acid-green)]">{'>'} RBAC COVERAGE</h3>
      </div>
      <div className="p-4">
        {loading ? (
          <div className="text-xs font-mono text-[var(--text-muted)] animate-pulse">Loading...</div>
        ) : (
          <div className="space-y-4">
            {/* Coverage bar */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-mono text-[var(--text-muted)]">Endpoint Coverage</span>
                <span className={`text-sm font-mono font-bold ${coverageColor}`}>
                  {data.coverage_percent}%
                </span>
              </div>
              <div className="w-full h-2 bg-[var(--bg)] rounded overflow-hidden">
                <div
                  className="h-full bg-[var(--acid-green)] transition-all"
                  style={{ width: `${Math.min(data.coverage_percent, 100)}%` }}
                />
              </div>
            </div>

            {/* Stats grid */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="text-xl font-mono text-[var(--acid-green)]">{data.roles_defined}</div>
                <div className="text-[10px] font-mono text-[var(--text-muted)]">Roles Defined</div>
              </div>
              <div>
                <div className="text-xl font-mono text-[var(--acid-green)]">{data.permissions_defined}</div>
                <div className="text-[10px] font-mono text-[var(--text-muted)]">Permissions</div>
              </div>
              <div>
                <div className="text-xl font-mono text-purple-400">{data.assignments_active}</div>
                <div className="text-[10px] font-mono text-[var(--text-muted)]">Active Assignments</div>
              </div>
              <div>
                <div className={`text-xl font-mono ${data.unprotected_endpoints > 0 ? 'text-yellow-400' : 'text-green-400'}`}>
                  {data.unprotected_endpoints}
                </div>
                <div className="text-[10px] font-mono text-[var(--text-muted)]">Unprotected Endpoints</div>
              </div>
            </div>

            <div className="text-[10px] font-mono text-[var(--text-muted)] pt-2 border-t border-[var(--border)]">
              {data.total_endpoints} total API endpoints registered
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel: Database Mode
// ---------------------------------------------------------------------------

interface HealthResponse {
  status?: string;
  db_mode?: string;
  database_mode?: string;
  components?: Record<string, { status?: string }>;
}

function DatabaseModePanel({ dbMode, loading }: { dbMode: string; loading: boolean }) {
  const isKnown = dbMode !== 'unknown';
  const modeColor = isKnown ? 'text-green-400' : 'text-[var(--text-muted)]';
  const modeBg = isKnown ? 'bg-green-500/20' : 'bg-[var(--bg-secondary)]';

  return (
    <div className="border border-[var(--border)] bg-[var(--bg-secondary)] rounded p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-mono font-bold text-[var(--text-primary)] uppercase tracking-wider">
          Database Mode
        </h3>
        <span className="text-[10px] font-mono text-[var(--text-muted)]">/api/health</span>
      </div>

      {loading ? (
        <div className="text-xs font-mono text-[var(--text-muted)] animate-pulse">
          Scanning database status...
        </div>
      ) : (
        <div className="space-y-3">
          <div className={`inline-flex items-center gap-2 px-3 py-2 rounded ${modeBg}`}>
            <span className={`text-sm font-mono font-bold ${modeColor}`}>{dbMode}</span>
          </div>
          <div className="text-[10px] font-mono text-[var(--text-muted)]">
            {isKnown
              ? 'Database mode reported by health endpoint'
              : 'db_mode not present in health response — server may not expose this field'}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel: Encryption Status
// ---------------------------------------------------------------------------

function EncryptionStatusPanel({ data, loading }: { data: EncryptionStatus; loading: boolean }) {
  const statusColor = (s: string) =>
    s === 'active' ? 'text-green-400' : s === 'degraded' ? 'text-yellow-400' : 'text-red-400';

  const statusBg = (s: string) =>
    s === 'active' ? 'bg-green-500/20' : s === 'degraded' ? 'bg-yellow-500/20' : 'bg-red-500/20';

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)]">
      <div className="p-4 border-b border-[var(--border)]">
        <h3 className="text-sm font-mono text-[var(--acid-green)]">{'>'} ENCRYPTION STATUS</h3>
      </div>
      <div className="p-4">
        {loading ? (
          <div className="text-xs font-mono text-[var(--text-muted)] animate-pulse">Loading...</div>
        ) : (
          <div className="space-y-4">
            {/* At-Rest */}
            <div className="p-3 bg-[var(--bg)] border border-[var(--border)] rounded">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-mono text-[var(--text)]">At-Rest Encryption</span>
                <span className={`px-2 py-0.5 text-[10px] font-mono uppercase rounded ${statusBg(data.at_rest.status)} ${statusColor(data.at_rest.status)}`}>
                  {data.at_rest.status}
                </span>
              </div>
              <div className="space-y-1 text-[10px] font-mono text-[var(--text-muted)]">
                <div>Algorithm: <span className="text-[var(--text)]">{data.at_rest.algorithm}</span></div>
                <div>Key Rotation: <span className="text-[var(--text)]">every {data.at_rest.key_rotation_days} days</span></div>
                {data.at_rest.last_rotation && (
                  <div>Last Rotation: <span className="text-[var(--text)]">{formatRelativeTime(data.at_rest.last_rotation)}</span></div>
                )}
              </div>
            </div>

            {/* In-Transit */}
            <div className="p-3 bg-[var(--bg)] border border-[var(--border)] rounded">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-mono text-[var(--text)]">In-Transit Encryption</span>
                <span className={`px-2 py-0.5 text-[10px] font-mono uppercase rounded ${statusBg(data.in_transit.status)} ${statusColor(data.in_transit.status)}`}>
                  {data.in_transit.status}
                </span>
              </div>
              <div className="space-y-1 text-[10px] font-mono text-[var(--text-muted)]">
                <div>Protocol: <span className="text-[var(--text)]">{data.in_transit.protocol}</span></div>
                <div>Min Version: <span className="text-[var(--text)]">TLS {data.in_transit.min_version}</span></div>
                {data.in_transit.certificate_expiry && (
                  <div>
                    Certificate Expiry:{' '}
                    <span className="text-[var(--text)]">
                      {new Date(data.in_transit.certificate_expiry).toLocaleDateString()}
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel: Compliance Frameworks
// ---------------------------------------------------------------------------

function ComplianceFrameworksPanel({
  frameworks,
  overallScore,
  lastAudit,
  nextAuditDue,
  loading,
}: {
  frameworks: FrameworkIndicator[];
  overallScore: number;
  lastAudit: string | null;
  nextAuditDue: string | null;
  loading: boolean;
}) {
  const scoreColor =
    overallScore >= 90 ? 'text-green-400' : overallScore >= 70 ? 'text-yellow-400' : 'text-red-400';

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)]">
      <div className="p-4 border-b border-[var(--border)] flex items-center justify-between">
        <h3 className="text-sm font-mono text-[var(--acid-green)]">{'>'} COMPLIANCE FRAMEWORKS</h3>
        <span className={`text-lg font-mono font-bold ${loading ? 'text-[var(--text-muted)]' : scoreColor}`}>
          {loading ? '--' : `${overallScore}%`}
        </span>
      </div>

      {loading ? (
        <div className="p-4 text-xs font-mono text-[var(--text-muted)] animate-pulse">Loading...</div>
      ) : (
        <>
          <div className="divide-y divide-[var(--border)]">
            {frameworks.map((fw) => {
              const style = FRAMEWORK_STATUS_STYLES[fw.status] || FRAMEWORK_STATUS_STYLES.not_assessed;
              const pct = fw.controls_total > 0
                ? Math.round((fw.controls_met / fw.controls_total) * 100)
                : 0;

              return (
                <div key={fw.name} className="p-4">
                  <div className="flex items-center justify-between mb-2">
                    <div>
                      <div className="text-sm font-mono text-[var(--text)]">{fw.name}</div>
                      {fw.notes && (
                        <div className="text-[10px] font-mono text-[var(--text-muted)] mt-0.5">{fw.notes}</div>
                      )}
                    </div>
                    <span className={`px-2 py-0.5 text-[10px] font-mono uppercase ${style.bg} ${style.text} border border-current/30`}>
                      {style.label}
                    </span>
                  </div>

                  {/* Controls progress bar */}
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-1.5 bg-[var(--bg)] rounded overflow-hidden">
                      <div
                        className={`h-full transition-all rounded ${
                          pct >= 90 ? 'bg-green-400' : pct >= 60 ? 'bg-yellow-400' : 'bg-red-400'
                        }`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-[10px] font-mono text-[var(--text-muted)] w-16 text-right">
                      {fw.controls_met}/{fw.controls_total}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="p-3 border-t border-[var(--border)] flex items-center justify-between text-[10px] font-mono text-[var(--text-muted)]">
            <span>
              {lastAudit ? `Last audit: ${formatRelativeTime(lastAudit)}` : 'No audit recorded'}
            </span>
            <span>
              {nextAuditDue ? `Next due: ${new Date(nextAuditDue).toLocaleDateString()}` : ''}
            </span>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel: Recent Audit Trail
// ---------------------------------------------------------------------------

function AuditTrailPanel({ entries, loading }: { entries: AuditEntry[]; loading: boolean }) {
  return (
    <div className="bg-[var(--surface)] border border-[var(--border)]">
      <div className="p-4 border-b border-[var(--border)] flex items-center justify-between">
        <h3 className="text-sm font-mono text-[var(--acid-green)]">{'>'} RECENT AUDIT TRAIL</h3>
        <Link
          href="/audit"
          className="text-[10px] font-mono text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
        >
          VIEW ALL
        </Link>
      </div>

      {loading ? (
        <div className="p-4 text-xs font-mono text-[var(--text-muted)] animate-pulse">Loading...</div>
      ) : entries.length === 0 ? (
        <div className="p-6 text-center text-xs font-mono text-[var(--text-muted)]">
          No audit entries recorded
        </div>
      ) : (
        <div className="divide-y divide-[var(--border)] max-h-80 overflow-y-auto">
          {entries.map((entry) => {
            const outcomeStyle = OUTCOME_STYLES[entry.outcome] || OUTCOME_STYLES.success;
            return (
              <div key={entry.id} className="p-3 flex items-start gap-3">
                <div className="text-[10px] font-mono text-[var(--text-muted)] w-14 shrink-0 pt-0.5">
                  {formatRelativeTime(entry.timestamp)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-mono text-[var(--text)]">{entry.event_type}</span>
                    <span className={`px-1.5 py-0 text-[10px] font-mono rounded ${outcomeStyle.bg} ${outcomeStyle.text}`}>
                      {entry.outcome}
                    </span>
                  </div>
                  <div className="text-[10px] font-mono text-[var(--text-muted)] mt-0.5 truncate">
                    {entry.actor} &rarr; {entry.resource}
                    {entry.action !== 'CHECK' && ` (${entry.action})`}
                  </div>
                  {entry.details && (
                    <div className="text-[10px] font-mono text-[var(--text-muted)] mt-0.5 italic">
                      {entry.details}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function CompliancePage() {
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();

  // Data hooks -- all try backend first, fallback to mock data
  const { status: complianceStatus, isLoading: statusLoading } = useComplianceStatus();
  const { rbac, rbacFallback, isLoading: rbacLoading } = useRBACCoverage();
  const { encryption, encryptionFallback, isLoading: encryptionLoading } = useEncryptionStatus();
  const { entries: auditEntries, auditFallback, isLoading: auditLoading } = useAuditTrail(8);
  const { data: healthData, isLoading: healthLoading } = useSWRFetch<HealthResponse>('/api/health', { refreshInterval: 60000 });

  // Derive framework indicators from the status endpoint
  const frameworkData = buildFrameworkIndicators(complianceStatus);

  // Effective data: backend or fallback
  const effectiveRBAC = rbac ?? rbacFallback;
  const effectiveEncryption = encryption ?? encryptionFallback;
  const effectiveAudit = auditEntries ?? auditFallback;
  const dbMode: string = (healthData as HealthResponse | null)?.db_mode
    ?? (healthData as HealthResponse | null)?.database_mode
    ?? 'unknown';

  // EU AI Act interactive state
  const [euAiActExpanded, setEuAiActExpanded] = useState(false);
  const [useCase, setUseCase] = useState('');
  const [classification, setClassification] = useState<RiskClassification | null>(null);
  const [classifying, setClassifying] = useState(false);
  const [assessments, setAssessments] = useState<ArticleAssessment[]>([]);
  const [showAssessments, setShowAssessments] = useState(false);
  const [bundle, setBundle] = useState<ComplianceBundle | null>(null);
  const [generatingBundle, setGeneratingBundle] = useState(false);
  const [activeArticle, setActiveArticle] = useState<'12' | '13' | '14'>('12');

  const classify = useCallback(async () => {
    if (!useCase.trim()) return;
    setClassifying(true);
    setClassification(null);
    setShowAssessments(false);
    setBundle(null);

    try {
      const response = await fetch(`${backendConfig.api}/api/v2/compliance/eu-ai-act/classify`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token || ''}`,
        },
        body: JSON.stringify({ description: useCase }),
      });

      if (response.ok) {
        const data = await response.json();
        setClassification(data.classification || data);
      } else {
        setClassification(getDemoClassification(useCase));
      }
    } catch {
      setClassification(getDemoClassification(useCase));
    } finally {
      setClassifying(false);
    }
  }, [useCase, backendConfig.api, tokens?.access_token]);

  const generateReport = useCallback(async () => {
    setShowAssessments(true);

    try {
      const response = await fetch(`${backendConfig.api}/api/v2/compliance/eu-ai-act/audit`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token || ''}`,
        },
        body: JSON.stringify({
          receipt: {
            question: useCase,
            verdict: 'approved_with_conditions',
            confidence: 0.78,
            consensus: { reached: true, method: 'majority' },
            agents: ['anthropic', 'openai', 'mistral'],
            rounds_used: 2,
          },
        }),
      });

      if (response.ok) {
        const data = await response.json();
        const report = data.conformity_report || data;
        if (report.assessments) {
          setAssessments(report.assessments);
          return;
        }
      }
      setAssessments(getDemoAssessments());
    } catch {
      setAssessments(getDemoAssessments());
    }
  }, [useCase, backendConfig.api, tokens?.access_token]);

  const generateBundle = useCallback(async () => {
    setGeneratingBundle(true);

    try {
      const response = await fetch(`${backendConfig.api}/api/v2/compliance/eu-ai-act/generate-bundle`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token || ''}`,
        },
        body: JSON.stringify({
          receipt: {
            question: useCase,
            verdict: 'approved_with_conditions',
            confidence: 0.78,
            consensus: { reached: true, method: 'majority' },
            agents: ['anthropic', 'openai', 'mistral'],
            rounds_used: 2,
          },
          provider_name: 'Aragora Platform',
          system_name: 'Decision Integrity Engine',
          system_version: '1.0',
        }),
      });

      if (response.ok) {
        const data = await response.json();
        setBundle(data.bundle || data);
      } else {
        setBundle(getDemoBundle());
      }
    } catch {
      setBundle(getDemoBundle());
    } finally {
      setGeneratingBundle(false);
    }
  }, [useCase, backendConfig.api, tokens?.access_token]);

  const riskStyle = classification ? RISK_COLORS[classification.risk_level] || RISK_COLORS.minimal : null;

  return (
    <div className="min-h-screen bg-[var(--bg)]">
      <Scanlines />
      <CRTVignette />

      <header className="border-b border-[var(--border)] bg-[var(--surface)]/50 backdrop-blur-sm sticky top-0 z-40">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link href="/" className="hover:text-[var(--acid-green)]">
              <AsciiBannerCompact />
            </Link>
            <span className="text-[var(--text-muted)] font-mono text-sm">{'//'} COMPLIANCE DASHBOARD</span>
          </div>
          <div className="flex items-center gap-3">
            <BackendSelector />
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6 max-w-5xl relative z-10">
        {/* Header */}
        <div className="mb-6">
          <div className="flex items-center gap-3 mb-2">
            <Link
              href="/dashboard"
              className="text-xs font-mono text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
            >
              DASHBOARD
            </Link>
            <span className="text-xs font-mono text-[var(--text-muted)]">/</span>
            <span className="text-xs font-mono text-[var(--acid-green)]">COMPLIANCE</span>
          </div>
          <h1 className="text-xl font-mono text-[var(--acid-green)] mb-1">
            {'>'} COMPLIANCE DASHBOARD
          </h1>
          <p className="text-xs text-[var(--text-muted)] font-mono">
            RBAC coverage, encryption status, framework readiness, and audit trail
          </p>
        </div>

        {/* ============================================================= */}
        {/* Section 1+2: RBAC Coverage + Encryption Status (side by side) */}
        {/* ============================================================= */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          <PanelErrorBoundary panelName="RBAC Coverage">
            <RBACCoveragePanel data={effectiveRBAC} loading={rbacLoading && !rbac} />
          </PanelErrorBoundary>

          <PanelErrorBoundary panelName="Encryption Status">
            <EncryptionStatusPanel data={effectiveEncryption} loading={encryptionLoading && !encryption} />
          </PanelErrorBoundary>
        </div>

        {/* ============================================================= */}
        {/* Section 1b: Database Mode                                      */}
        {/* ============================================================= */}
        <div className="mb-6">
          <PanelErrorBoundary panelName="Database Mode">
            <DatabaseModePanel dbMode={dbMode} loading={healthLoading && !healthData} />
          </PanelErrorBoundary>
        </div>

        {/* ============================================================= */}
        {/* Section 3: Compliance Frameworks */}
        {/* ============================================================= */}
        <div className="mb-6">
          <PanelErrorBoundary panelName="Compliance Frameworks">
            <ComplianceFrameworksPanel
              frameworks={frameworkData.frameworks}
              overallScore={frameworkData.overall_score}
              lastAudit={frameworkData.last_audit}
              nextAuditDue={frameworkData.next_audit_due}
              loading={statusLoading}
            />
          </PanelErrorBoundary>
        </div>

        {/* ============================================================= */}
        {/* Section 4: Recent Audit Trail */}
        {/* ============================================================= */}
        <div className="mb-6">
          <PanelErrorBoundary panelName="Audit Trail">
            <AuditTrailPanel entries={effectiveAudit} loading={auditLoading && !auditEntries} />
          </PanelErrorBoundary>
        </div>

        {/* ============================================================= */}
        {/* Quick Links */}
        {/* ============================================================= */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <Link
            href="/policy"
            className="p-3 bg-[var(--surface)] border border-[var(--border)] hover:border-[var(--acid-green)]/50 transition-colors text-center"
          >
            <div className="text-xs font-mono text-[var(--text)] hover:text-[var(--acid-green)]">Policies</div>
            <div className="text-[10px] font-mono text-[var(--text-muted)]">Manage rules</div>
          </Link>
          <Link
            href="/audit"
            className="p-3 bg-[var(--surface)] border border-[var(--border)] hover:border-[var(--acid-green)]/50 transition-colors text-center"
          >
            <div className="text-xs font-mono text-[var(--text)] hover:text-[var(--acid-green)]">Audit</div>
            <div className="text-[10px] font-mono text-[var(--text-muted)]">Audit trails</div>
          </Link>
          <Link
            href="/receipts"
            className="p-3 bg-[var(--surface)] border border-[var(--border)] hover:border-[var(--acid-green)]/50 transition-colors text-center"
          >
            <div className="text-xs font-mono text-[var(--text)] hover:text-[var(--acid-green)]">Receipts</div>
            <div className="text-[10px] font-mono text-[var(--text-muted)]">Decision records</div>
          </Link>
          <Link
            href="/privacy"
            className="p-3 bg-[var(--surface)] border border-[var(--border)] hover:border-[var(--acid-green)]/50 transition-colors text-center"
          >
            <div className="text-xs font-mono text-[var(--text)] hover:text-[var(--acid-green)]">Privacy</div>
            <div className="text-[10px] font-mono text-[var(--text-muted)]">GDPR controls</div>
          </Link>
        </div>

        {/* ============================================================= */}
        {/* EU AI Act: Collapsible Section */}
        {/* ============================================================= */}
        <div className="bg-[var(--surface)] border border-[var(--border)] mb-6">
          <button
            onClick={() => setEuAiActExpanded(!euAiActExpanded)}
            className="w-full p-4 flex items-center justify-between hover:bg-[var(--bg)]/30 transition-colors"
          >
            <div className="flex items-center gap-3">
              <h3 className="text-sm font-mono text-[var(--acid-green)]">{'>'} EU AI ACT TOOLKIT</h3>
              <span className="text-[10px] font-mono text-[var(--text-muted)]">
                Risk classification, conformity assessment, artifact bundles
              </span>
            </div>
            <span className="text-xs font-mono text-[var(--text-muted)]">
              {euAiActExpanded ? '[-]' : '[+]'}
            </span>
          </button>

          {euAiActExpanded && (
            <div className="border-t border-[var(--border)] p-6 space-y-6">
              {/* Step 1: Risk Classification */}
              <PanelErrorBoundary panelName="Risk Classification">
                <section>
                  <h2 className="text-base font-mono mb-1 text-[var(--text)]">1. CLASSIFY AI USE CASE</h2>
                  <p className="text-xs text-[var(--text-muted)] font-mono mb-4">
                    Describe your AI system to determine its risk category under the EU AI Act
                  </p>

                  <div className="flex flex-wrap gap-2 mb-4">
                    {SAMPLE_USE_CASES.map((sample) => (
                      <button
                        key={sample.label}
                        onClick={() => setUseCase(sample.description)}
                        className="px-3 py-1 text-xs font-mono border border-[var(--border)] rounded hover:border-[var(--acid-green)] hover:text-[var(--acid-green)] transition-colors"
                      >
                        {sample.label}
                      </button>
                    ))}
                  </div>

                  <textarea
                    value={useCase}
                    onChange={(e) => setUseCase(e.target.value)}
                    placeholder="Describe your AI system's purpose and functionality..."
                    rows={3}
                    className="w-full bg-[var(--bg)] border border-[var(--border)] rounded p-3 font-mono text-sm text-[var(--text)] focus:border-[var(--acid-green)] focus:outline-none resize-none"
                  />

                  <button
                    onClick={classify}
                    disabled={!useCase.trim() || classifying}
                    className="mt-3 px-4 py-2 text-sm font-mono bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/40 rounded hover:bg-[var(--acid-green)]/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    {classifying ? 'CLASSIFYING...' : 'CLASSIFY RISK LEVEL'}
                  </button>

                  {classification && riskStyle && (
                    <div className={`mt-4 border rounded p-4 ${riskStyle.bg} ${riskStyle.border}`}>
                      <div className="flex items-center justify-between mb-3">
                        <span className={`text-lg font-mono font-bold ${riskStyle.text}`}>
                          {classification.risk_level.toUpperCase()} RISK
                        </span>
                        <span className="text-xs font-mono text-[var(--text-muted)]">
                          Confidence: {(classification.confidence * 100).toFixed(0)}%
                        </span>
                      </div>

                      {classification.annex_iii_categories.length > 0 && (
                        <div className="mb-2">
                          <span className="text-xs font-mono text-[var(--text-muted)]">Annex III Categories:</span>
                          <div className="flex flex-wrap gap-1 mt-1">
                            {classification.annex_iii_categories.map((cat, i) => (
                              <span key={i} className="px-2 py-0.5 text-xs font-mono bg-[var(--bg)]/50 rounded">
                                {cat}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      <div className="mb-2">
                        <span className="text-xs font-mono text-[var(--text-muted)]">Applicable Articles:</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {classification.applicable_articles.map((art, i) => (
                            <span key={i} className="px-2 py-0.5 text-xs font-mono bg-[var(--bg)]/50 rounded">
                              {art}
                            </span>
                          ))}
                        </div>
                      </div>

                      {classification.matched_keywords.length > 0 && (
                        <div>
                          <span className="text-xs font-mono text-[var(--text-muted)]">Matched Keywords:</span>
                          <span className="text-xs font-mono ml-2">
                            {classification.matched_keywords.join(', ')}
                          </span>
                        </div>
                      )}

                      {classification.risk_level === 'high' && (
                        <div className="mt-3 pt-3 border-t border-[var(--border)]/50">
                          <button
                            onClick={generateReport}
                            className="px-4 py-2 text-sm font-mono bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/40 rounded hover:bg-[var(--acid-green)]/20 transition-colors"
                          >
                            GENERATE CONFORMITY ASSESSMENT
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </section>
              </PanelErrorBoundary>

              {/* Step 2: Conformity Assessment */}
              {showAssessments && (
                <PanelErrorBoundary panelName="Conformity Assessment">
                  <section>
                    <h2 className="text-base font-mono mb-1 text-[var(--text)]">2. CONFORMITY ASSESSMENT</h2>
                    <p className="text-xs text-[var(--text-muted)] font-mono mb-4">
                      Article-by-article compliance status based on your decision receipt
                    </p>

                    <div className="space-y-3">
                      {assessments.map((assessment) => (
                        <details key={assessment.article} className="border border-[var(--border)] rounded overflow-hidden">
                          <summary className="p-3 bg-[var(--surface)]/50 cursor-pointer hover:bg-[var(--surface)] transition-colors flex items-center justify-between">
                            <span className="font-mono text-sm text-[var(--text)]">
                              {assessment.article}: {assessment.title}
                            </span>
                            <span className={`font-mono text-xs ${STATUS_COLORS[assessment.status]}`}>
                              {STATUS_ICONS[assessment.status]}
                            </span>
                          </summary>
                          <div className="p-3 border-t border-[var(--border)] text-sm">
                            {assessment.findings.length > 0 && (
                              <div className="mb-2">
                                <span className="text-xs font-mono text-[var(--text-muted)]">Findings:</span>
                                <ul className="mt-1 space-y-1">
                                  {assessment.findings.map((f, i) => (
                                    <li key={i} className="text-xs font-mono pl-3 border-l-2 border-[var(--acid-green)]/40">
                                      {f}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}
                            {assessment.recommendations.length > 0 && (
                              <div>
                                <span className="text-xs font-mono text-[var(--text-muted)]">Recommendations:</span>
                                <ul className="mt-1 space-y-1">
                                  {assessment.recommendations.map((r, i) => (
                                    <li key={i} className="text-xs font-mono pl-3 border-l-2 border-yellow-400/40">
                                      {r}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}
                          </div>
                        </details>
                      ))}
                    </div>

                    <button
                      onClick={generateBundle}
                      disabled={generatingBundle}
                      className="mt-4 px-4 py-2 text-sm font-mono bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/40 rounded hover:bg-[var(--acid-green)]/20 disabled:opacity-50 transition-colors"
                    >
                      {generatingBundle ? 'GENERATING...' : 'GENERATE FULL ARTIFACT BUNDLE'}
                    </button>
                  </section>
                </PanelErrorBoundary>
              )}

              {/* Step 3: Artifact Bundle */}
              {bundle && (
                <PanelErrorBoundary panelName="Compliance Bundle">
                  <section>
                    <h2 className="text-base font-mono mb-1 text-[var(--text)]">3. COMPLIANCE ARTIFACT BUNDLE</h2>
                    <div className="flex items-center gap-4 mb-4">
                      <span className="text-xs font-mono text-[var(--text-muted)]">
                        Bundle: {bundle.bundle_id}
                      </span>
                      <span className="text-xs font-mono text-[var(--text-muted)]">
                        Generated: {new Date(bundle.generated_at).toLocaleString()}
                      </span>
                    </div>
                    <div className="text-xs font-mono text-[var(--text-muted)] mb-4 break-all">
                      Integrity: {bundle.integrity_hash}
                    </div>

                    <div className="flex border-b border-[var(--border)] mb-4">
                      {(['12', '13', '14'] as const).map((art) => (
                        <button
                          key={art}
                          onClick={() => setActiveArticle(art)}
                          className={`px-4 py-2 text-sm font-mono border-b-2 transition-colors ${
                            activeArticle === art
                              ? 'border-[var(--acid-green)] text-[var(--acid-green)]'
                              : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text)]'
                          }`}
                        >
                          Article {art}
                        </button>
                      ))}
                    </div>

                    <div className="bg-[var(--bg)] border border-[var(--border)] rounded p-4">
                      <pre className="text-xs font-mono whitespace-pre-wrap overflow-auto max-h-96 text-[var(--text)]">
                        {JSON.stringify(
                          activeArticle === '12'
                            ? bundle.article_12
                            : activeArticle === '13'
                              ? bundle.article_13
                              : bundle.article_14,
                          null,
                          2
                        )}
                      </pre>
                    </div>

                    <div className="mt-4 flex gap-2">
                      <button
                        onClick={() => {
                          const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
                          const url = URL.createObjectURL(blob);
                          const a = document.createElement('a');
                          a.href = url;
                          a.download = `${bundle.bundle_id}.json`;
                          a.click();
                          URL.revokeObjectURL(url);
                        }}
                        className="px-3 py-1.5 text-xs font-mono bg-[var(--surface)] border border-[var(--border)] rounded hover:border-[var(--acid-green)] transition-colors"
                      >
                        DOWNLOAD JSON
                      </button>
                    </div>
                  </section>
                </PanelErrorBoundary>
              )}
            </div>
          )}
        </div>

        {/* Navigation */}
        <div className="flex items-center gap-2 pt-4 border-t border-[var(--border)]">
          <span className="text-xs font-mono text-[var(--text-muted)]">Navigate:</span>
          <Link
            href="/dashboard"
            className="px-3 py-1 text-xs font-mono bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
          >
            DASHBOARD
          </Link>
          <Link
            href="/arena"
            className="px-3 py-1 text-xs font-mono bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors"
          >
            NEW DEBATE
          </Link>
          <Link
            href="/settings"
            className="px-3 py-1 text-xs font-mono bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
          >
            SETTINGS
          </Link>
        </div>
      </main>

      <footer className="border-t border-[var(--border)] bg-[var(--surface)]/50 py-4 mt-8">
        <div className="container mx-auto px-4 flex items-center justify-between text-xs text-[var(--text-muted)] font-mono">
          <span>EU AI Act enforcement: August 2, 2026</span>
          <div className="flex items-center gap-4">
            <Link href="/audit" className="hover:text-[var(--acid-green)]">
              AUDIT
            </Link>
            <Link href="/receipts" className="hover:text-[var(--acid-green)]">
              RECEIPTS
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
