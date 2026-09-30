'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useSWRFetch } from '@/hooks/useSWRFetch';

// ---------------------------------------------------------------------------
// Types matching data_classification_handler.py response shapes
// ---------------------------------------------------------------------------

type ClassificationLevel = 'public' | 'internal' | 'confidential' | 'restricted' | 'pii';

interface PolicyRule {
  classification: ClassificationLevel;
  allowed_operations: string[];
  requires_encryption: boolean;
  requires_consent: boolean;
  allowed_regions: string[];
  retention_days: number;
  [key: string]: unknown;
}

interface ActivePolicy {
  levels: Record<ClassificationLevel, PolicyRule>;
  version?: string;
  updated_at?: string;
  [key: string]: unknown;
}

interface ClassifyResult {
  classification: ClassificationLevel;
  confidence: number;
  matched_patterns: string[];
  has_pii: boolean;
  recommendations: string[];
  [key: string]: unknown;
}

interface ValidateResult {
  allowed: boolean;
  classification: ClassificationLevel;
  operation: string;
  violations: string[];
  requirements_met: Record<string, boolean>;
  [key: string]: unknown;
}

interface EnforceResult {
  allowed: boolean;
  source_classification: ClassificationLevel;
  target_classification: ClassificationLevel;
  operation: string;
  violations: string[];
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CLASSIFICATION_LEVELS: ClassificationLevel[] = [
  'public',
  'internal',
  'confidential',
  'restricted',
  'pii',
];

const LEVEL_COLORS: Record<ClassificationLevel, string> = {
  public: 'text-[var(--acid-green)] bg-[var(--acid-green)]/10 border-[var(--acid-green)]/30',
  internal: 'text-[var(--acid-cyan)] bg-[var(--acid-cyan)]/10 border-[var(--acid-cyan)]/30',
  confidential: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
  restricted: 'text-orange-400 bg-orange-500/10 border-orange-500/30',
  pii: 'text-red-400 bg-red-500/10 border-red-500/30',
};

const LEVEL_SEVERITY_ORDER: Record<ClassificationLevel, number> = {
  public: 0,
  internal: 1,
  confidential: 2,
  restricted: 3,
  pii: 4,
};

function LevelBadge({ level }: { level: ClassificationLevel }) {
  const style = LEVEL_COLORS[level] || LEVEL_COLORS.public;
  return (
    <span className={`px-2 py-0.5 text-[10px] font-theme-data uppercase rounded border ${style}`}>
      {level}
    </span>
  );
}

function SeverityMeter({ level }: { level: ClassificationLevel }) {
  const severity = LEVEL_SEVERITY_ORDER[level] ?? 0;
  const segments = 5;

  return (
    <div className="flex gap-0.5" title={`Severity: ${severity + 1}/${segments}`}>
      {Array.from({ length: segments }, (_, i) => (
        <div
          key={i}
          className={`w-3 h-2 rounded-sm transition-colors ${
            i <= severity
              ? severity >= 3
                ? 'bg-red-400'
                : severity >= 2
                  ? 'bg-yellow-400'
                  : 'bg-[var(--acid-green)]'
              : 'bg-[var(--border)]'
          }`}
        />
      ))}
    </div>
  );
}

function BoolIndicator({
  value,
  trueLabel,
  falseLabel,
}: {
  value: boolean;
  trueLabel?: string;
  falseLabel?: string;
}) {
  return (
    <span
      className={`text-xs font-theme-data ${value ? 'text-[var(--acid-green)]' : 'text-[var(--text-muted)]'}`}
    >
      {value ? (trueLabel ?? 'YES') : (falseLabel ?? 'NO')}
    </span>
  );
}

// ---------------------------------------------------------------------------
// API Helpers
// ---------------------------------------------------------------------------

const API_BASE = '/api/v1/data-classification';

async function apiPost<T>(endpoint: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(`${API_BASE}/${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || `Request failed: ${res.status}`);
  }
  const json = await res.json();
  return json.data ?? json;
}

// ---------------------------------------------------------------------------
// Page Component
// ---------------------------------------------------------------------------

type ActiveTab = 'policy' | 'classify' | 'validate' | 'enforce';

export default function DataClassificationPage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('policy');

  // Fetch active policy
  const {
    data: policyResponse,
    isLoading: policyLoading,
    error: policyError,
  } = useSWRFetch<{ data: ActivePolicy }>(`${API_BASE}/policy`);

  const policy = policyResponse?.data;

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
                href="/compliance"
                className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
              >
                Compliance
              </Link>
              <span className="text-[var(--text-muted)]">/</span>
              <span className="text-xs font-theme-data text-[var(--acid-green)]">
                Data Classification
              </span>
            </div>
            <h1 className="text-xl font-theme-data text-[var(--acid-green)]">
              {'>'} DATA CLASSIFICATION
            </h1>
            <p className="text-xs text-[var(--text-muted)] font-theme-data mt-1">
              Classify, validate, and enforce data handling policies. Five sensitivity levels from
              public to PII with automated compliance checking.
            </p>
          </div>

          {/* Error State */}
          {policyError && (
            <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 text-red-400 font-theme-data text-sm">
              Failed to load classification policy. The data classification module may not be
              available.
            </div>
          )}

          {/* Tabs */}
          <div className="flex gap-2 mb-6 flex-wrap">
            {[
              { key: 'policy' as const, label: 'POLICY' },
              { key: 'classify' as const, label: 'CLASSIFY' },
              { key: 'validate' as const, label: 'VALIDATE' },
              { key: 'enforce' as const, label: 'ENFORCE' },
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

          <PanelErrorBoundary panelName="Data Classification">
            {activeTab === 'policy' && <PolicyTab policy={policy} loading={policyLoading} />}
            {activeTab === 'classify' && <ClassifyTab />}
            {activeTab === 'validate' && <ValidateTab />}
            {activeTab === 'enforce' && <EnforceTab />}
          </PanelErrorBoundary>

          {/* Quick Links */}
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              href="/compliance"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Compliance
            </Link>
            <Link
              href="/audit-trail"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Audit Trail
            </Link>
            <Link
              href="/backup"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Backup & DR
            </Link>
          </div>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--acid-green)]/20 mt-8">
          <div className="text-[var(--acid-green)]/50 mb-2" aria-hidden="true">
            {'='.repeat(40)}
          </div>
          <p className="text-[var(--text-muted)]">{'>'} ARAGORA // DATA CLASSIFICATION</p>
        </footer>
      </main>
    </>
  );
}

// ---------------------------------------------------------------------------
// Policy Tab
// ---------------------------------------------------------------------------

function PolicyTab({ policy, loading }: { policy: ActivePolicy | undefined; loading: boolean }) {
  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-[var(--text-muted)] font-theme-data animate-pulse">
        Loading classification policy...
      </div>
    );
  }

  if (!policy) {
    return (
      <div className="p-6 bg-[var(--surface)] border border-[var(--border)] text-center">
        <p className="text-sm font-theme-data text-[var(--text-muted)]">
          No active policy loaded. Start the server with the data classification module enabled.
        </p>
      </div>
    );
  }

  const levels = policy.levels
    ? Object.entries(policy.levels).sort(
        ([a], [b]) =>
          (LEVEL_SEVERITY_ORDER[a as ClassificationLevel] ?? 0) -
          (LEVEL_SEVERITY_ORDER[b as ClassificationLevel] ?? 0),
      )
    : [];

  return (
    <div>
      {/* Policy Metadata */}
      <div className="flex gap-4 mb-6 text-xs font-theme-data text-[var(--text-muted)]">
        {policy.version && <span>Version: {policy.version}</span>}
        {policy.updated_at && <span>Updated: {new Date(policy.updated_at).toLocaleString()}</span>}
        <span>{levels.length} levels configured</span>
      </div>

      {/* Level Cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
        {levels.map(([level, rule]) => {
          const typedLevel = level as ClassificationLevel;
          const typedRule = rule as PolicyRule;

          return (
            <div
              key={level}
              className="p-4 bg-[var(--surface)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              <div className="flex items-center justify-between mb-3">
                <LevelBadge level={typedLevel} />
                <SeverityMeter level={typedLevel} />
              </div>

              <div className="space-y-2 text-xs font-theme-data">
                {/* Allowed Operations */}
                <div>
                  <span className="text-[var(--text-muted)] uppercase text-[10px]">
                    Operations:
                  </span>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {(typedRule.allowed_operations ?? []).map((op) => (
                      <span
                        key={op}
                        className="px-1.5 py-0.5 text-[10px] bg-[var(--bg)] border border-[var(--border)] text-[var(--text)]"
                      >
                        {op}
                      </span>
                    ))}
                    {(!typedRule.allowed_operations ||
                      typedRule.allowed_operations.length === 0) && (
                      <span className="text-[var(--text-muted)]">None</span>
                    )}
                  </div>
                </div>

                {/* Requirements */}
                <div className="flex gap-4">
                  <div>
                    <span className="text-[var(--text-muted)] uppercase text-[10px]">
                      Encryption:
                    </span>{' '}
                    <BoolIndicator
                      value={typedRule.requires_encryption}
                      trueLabel="REQUIRED"
                      falseLabel="OPTIONAL"
                    />
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)] uppercase text-[10px]">Consent:</span>{' '}
                    <BoolIndicator
                      value={typedRule.requires_consent}
                      trueLabel="REQUIRED"
                      falseLabel="OPTIONAL"
                    />
                  </div>
                </div>

                {/* Regions */}
                {typedRule.allowed_regions && typedRule.allowed_regions.length > 0 && (
                  <div>
                    <span className="text-[var(--text-muted)] uppercase text-[10px]">Regions:</span>{' '}
                    <span className="text-[var(--acid-cyan)]">
                      {typedRule.allowed_regions.join(', ')}
                    </span>
                  </div>
                )}

                {/* Retention */}
                {typedRule.retention_days != null && (
                  <div>
                    <span className="text-[var(--text-muted)] uppercase text-[10px]">
                      Retention:
                    </span>{' '}
                    <span className="text-[var(--text)]">{typedRule.retention_days} days</span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Raw policy fallback when levels not structured */}
      {levels.length === 0 && (
        <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
          <h3 className="text-sm font-theme-data text-[var(--acid-green)] uppercase mb-3">
            Raw Policy
          </h3>
          <pre className="text-xs font-theme-data text-[var(--text-muted)] overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(policy, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Classify Tab
// ---------------------------------------------------------------------------

function ClassifyTab() {
  const [dataInput, setDataInput] = useState('');
  const [context, setContext] = useState('');
  const [result, setResult] = useState<ClassifyResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClassify = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      let parsedData: Record<string, unknown>;
      try {
        parsedData = JSON.parse(dataInput);
      } catch {
        // Treat as text content with a "content" key
        parsedData = { content: dataInput };
      }

      const res = await apiPost<ClassifyResult>('classify', {
        data: parsedData,
        context: context || undefined,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Classification failed');
    } finally {
      setLoading(false);
    }
  }, [dataInput, context]);

  return (
    <div className="space-y-6">
      {/* Input */}
      <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] uppercase mb-3">
          Classify Data
        </h3>
        <p className="text-xs font-theme-data text-[var(--text-muted)] mb-4">
          Paste JSON data or plain text to classify. The classifier detects PII patterns,
          sensitivity markers, and content characteristics.
        </p>

        <div className="space-y-3">
          <div>
            <label className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase block mb-1">
              Data (JSON or text)
            </label>
            <textarea
              value={dataInput}
              onChange={(e) => setDataInput(e.target.value)}
              placeholder='{"name": "John Doe", "email": "john@example.com", "ssn": "123-45-6789"}'
              rows={6}
              className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs font-theme-data rounded focus:outline-none focus:border-[var(--acid-green)]/50 resize-y"
            />
          </div>
          <div>
            <label className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase block mb-1">
              Context (optional)
            </label>
            <input
              type="text"
              value={context}
              onChange={(e) => setContext(e.target.value)}
              placeholder="e.g. user registration form, medical records, public blog"
              className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs font-theme-data rounded focus:outline-none focus:border-[var(--acid-green)]/50"
            />
          </div>
          <button
            onClick={handleClassify}
            disabled={loading || !dataInput.trim()}
            className="px-4 py-2 font-theme-data text-sm border border-[var(--acid-green)] text-[var(--acid-green)] hover:bg-[var(--acid-green)]/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {loading ? '[CLASSIFYING...]' : '[CLASSIFY]'}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-400 font-theme-data text-sm">
          {error}
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
          <h3 className="text-sm font-theme-data text-[var(--acid-green)] uppercase mb-4">
            Classification Result
          </h3>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <div className="text-center">
              <div className="mb-1">
                <LevelBadge level={result.classification} />
              </div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                Level
              </div>
            </div>
            <div className="text-center">
              <div
                className={`text-lg font-theme-data ${
                  (result.confidence ?? 0) >= 0.9
                    ? 'text-[var(--acid-green)]'
                    : (result.confidence ?? 0) >= 0.7
                      ? 'text-yellow-400'
                      : 'text-red-400'
                }`}
              >
                {result.confidence != null ? `${(result.confidence * 100).toFixed(1)}%` : '--'}
              </div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                Confidence
              </div>
            </div>
            <div className="text-center">
              <div
                className={`text-lg font-theme-data ${result.has_pii ? 'text-red-400' : 'text-[var(--acid-green)]'}`}
              >
                {result.has_pii ? 'DETECTED' : 'NONE'}
              </div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                PII
              </div>
            </div>
            <div className="text-center">
              <SeverityMeter level={result.classification} />
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mt-1">
                Severity
              </div>
            </div>
          </div>

          {/* Matched Patterns */}
          {result.matched_patterns && result.matched_patterns.length > 0 && (
            <div className="mb-3">
              <span className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                Matched Patterns:
              </span>
              <div className="flex flex-wrap gap-1 mt-1">
                {result.matched_patterns.map((p) => (
                  <span
                    key={p}
                    className="px-1.5 py-0.5 text-[10px] font-theme-data bg-red-500/10 border border-red-500/30 text-red-400"
                  >
                    {p}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Recommendations */}
          {result.recommendations && result.recommendations.length > 0 && (
            <div>
              <span className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                Recommendations:
              </span>
              <ul className="mt-1 space-y-1">
                {result.recommendations.map((r, i) => (
                  <li
                    key={i}
                    className="text-xs font-theme-data text-[var(--acid-cyan)] flex items-start gap-2"
                  >
                    <span className="text-[var(--text-muted)]">-</span> {r}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Validate Tab
// ---------------------------------------------------------------------------

function ValidateTab() {
  const [classification, setClassification] = useState<ClassificationLevel>('internal');
  const [operation, setOperation] = useState('read');
  const [region, setRegion] = useState('');
  const [hasConsent, setHasConsent] = useState(false);
  const [isEncrypted, setIsEncrypted] = useState(false);
  const [result, setResult] = useState<ValidateResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleValidate = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await apiPost<ValidateResult>('validate', {
        data: { _sample: true },
        classification,
        operation,
        region: region || undefined,
        has_consent: hasConsent,
        is_encrypted: isEncrypted,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Validation failed');
    } finally {
      setLoading(false);
    }
  }, [classification, operation, region, hasConsent, isEncrypted]);

  return (
    <div className="space-y-6">
      {/* Input */}
      <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] uppercase mb-3">
          Validate Handling Operation
        </h3>
        <p className="text-xs font-theme-data text-[var(--text-muted)] mb-4">
          Check whether a specific operation is permitted for a given classification level and
          handling context.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase block mb-1">
              Classification Level
            </label>
            <select
              value={classification}
              onChange={(e) => setClassification(e.target.value as ClassificationLevel)}
              className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs font-theme-data rounded focus:outline-none focus:border-[var(--acid-green)]/50"
            >
              {CLASSIFICATION_LEVELS.map((l) => (
                <option key={l} value={l}>
                  {l.toUpperCase()}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase block mb-1">
              Operation
            </label>
            <select
              value={operation}
              onChange={(e) => setOperation(e.target.value)}
              className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs font-theme-data rounded focus:outline-none focus:border-[var(--acid-green)]/50"
            >
              <option value="read">read</option>
              <option value="write">write</option>
              <option value="export">export</option>
              <option value="share">share</option>
              <option value="delete">delete</option>
              <option value="archive">archive</option>
            </select>
          </div>

          <div>
            <label className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase block mb-1">
              Region (optional)
            </label>
            <input
              type="text"
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              placeholder="e.g. us-east-1, eu-west-1"
              className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs font-theme-data rounded focus:outline-none focus:border-[var(--acid-green)]/50"
            />
          </div>

          <div className="flex gap-6 items-end pb-1">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={hasConsent}
                onChange={(e) => setHasConsent(e.target.checked)}
                className="accent-[var(--acid-green)]"
              />
              <span className="text-xs font-theme-data text-[var(--text)]">Has Consent</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={isEncrypted}
                onChange={(e) => setIsEncrypted(e.target.checked)}
                className="accent-[var(--acid-green)]"
              />
              <span className="text-xs font-theme-data text-[var(--text)]">Encrypted</span>
            </label>
          </div>
        </div>

        <button
          onClick={handleValidate}
          disabled={loading}
          className="mt-4 px-4 py-2 font-theme-data text-sm border border-[var(--acid-green)] text-[var(--acid-green)] hover:bg-[var(--acid-green)]/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {loading ? '[VALIDATING...]' : '[VALIDATE]'}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-400 font-theme-data text-sm">
          {error}
        </div>
      )}

      {/* Result */}
      {result && (
        <div
          className={`p-4 border ${
            result.allowed
              ? 'bg-[var(--acid-green)]/5 border-[var(--acid-green)]/30'
              : 'bg-red-500/5 border-red-500/30'
          }`}
        >
          <div className="flex items-center gap-3 mb-4">
            <span
              className={`text-xl font-theme-data ${result.allowed ? 'text-[var(--acid-green)]' : 'text-red-400'}`}
            >
              {result.allowed ? '[ALLOWED]' : '[DENIED]'}
            </span>
            <LevelBadge level={result.classification} />
            <span className="text-xs font-theme-data text-[var(--text-muted)]">
              {result.operation}
            </span>
          </div>

          {/* Violations */}
          {result.violations && result.violations.length > 0 && (
            <div className="mb-3">
              <span className="text-[10px] font-theme-data text-red-400 uppercase">
                Violations:
              </span>
              <ul className="mt-1 space-y-1">
                {result.violations.map((v, i) => (
                  <li
                    key={i}
                    className="text-xs font-theme-data text-red-400 flex items-start gap-2"
                  >
                    <span className="text-red-400/50">!</span> {v}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Requirements Met */}
          {result.requirements_met && Object.keys(result.requirements_met).length > 0 && (
            <div>
              <span className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                Requirements:
              </span>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mt-1">
                {Object.entries(result.requirements_met).map(([req, met]) => (
                  <div key={req} className="flex items-center gap-2">
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${met ? 'bg-[var(--acid-green)]' : 'bg-red-400'}`}
                    />
                    <span className="text-xs font-theme-data text-[var(--text)]">{req}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Enforce Tab
// ---------------------------------------------------------------------------

function EnforceTab() {
  const [sourceLevel, setSourceLevel] = useState<ClassificationLevel>('confidential');
  const [targetLevel, setTargetLevel] = useState<ClassificationLevel>('internal');
  const [operation, setOperation] = useState('read');
  const [region, setRegion] = useState('');
  const [hasConsent, setHasConsent] = useState(false);
  const [isEncrypted, setIsEncrypted] = useState(false);
  const [result, setResult] = useState<EnforceResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleEnforce = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await apiPost<EnforceResult>('enforce', {
        data: { _sample: true },
        source_classification: sourceLevel,
        target_classification: targetLevel,
        operation,
        region: region || undefined,
        has_consent: hasConsent,
        is_encrypted: isEncrypted,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Enforcement check failed');
    } finally {
      setLoading(false);
    }
  }, [sourceLevel, targetLevel, operation, region, hasConsent, isEncrypted]);

  return (
    <div className="space-y-6">
      {/* Input */}
      <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] uppercase mb-3">
          Enforce Cross-Context Access
        </h3>
        <p className="text-xs font-theme-data text-[var(--text-muted)] mb-4">
          Validate whether data can flow between classification contexts. Checks if the
          source-to-target transfer meets all policy requirements.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase block mb-1">
              Source Classification
            </label>
            <select
              value={sourceLevel}
              onChange={(e) => setSourceLevel(e.target.value as ClassificationLevel)}
              className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs font-theme-data rounded focus:outline-none focus:border-[var(--acid-green)]/50"
            >
              {CLASSIFICATION_LEVELS.map((l) => (
                <option key={l} value={l}>
                  {l.toUpperCase()}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase block mb-1">
              Target Classification
            </label>
            <select
              value={targetLevel}
              onChange={(e) => setTargetLevel(e.target.value as ClassificationLevel)}
              className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs font-theme-data rounded focus:outline-none focus:border-[var(--acid-green)]/50"
            >
              {CLASSIFICATION_LEVELS.map((l) => (
                <option key={l} value={l}>
                  {l.toUpperCase()}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase block mb-1">
              Operation
            </label>
            <select
              value={operation}
              onChange={(e) => setOperation(e.target.value)}
              className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs font-theme-data rounded focus:outline-none focus:border-[var(--acid-green)]/50"
            >
              <option value="read">read</option>
              <option value="write">write</option>
              <option value="export">export</option>
              <option value="share">share</option>
              <option value="migrate">migrate</option>
            </select>
          </div>

          <div>
            <label className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase block mb-1">
              Region (optional)
            </label>
            <input
              type="text"
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              placeholder="e.g. us-east-1, eu-west-1"
              className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs font-theme-data rounded focus:outline-none focus:border-[var(--acid-green)]/50"
            />
          </div>

          <div className="flex gap-6 items-end pb-1">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={hasConsent}
                onChange={(e) => setHasConsent(e.target.checked)}
                className="accent-[var(--acid-green)]"
              />
              <span className="text-xs font-theme-data text-[var(--text)]">Has Consent</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={isEncrypted}
                onChange={(e) => setIsEncrypted(e.target.checked)}
                className="accent-[var(--acid-green)]"
              />
              <span className="text-xs font-theme-data text-[var(--text)]">Encrypted</span>
            </label>
          </div>
        </div>

        {/* Visual flow indicator */}
        <div className="flex items-center gap-3 mt-4 mb-4 text-xs font-theme-data">
          <LevelBadge level={sourceLevel} />
          <span className="text-[var(--acid-green)]">
            {'-->'} {operation.toUpperCase()} {'-->'}
          </span>
          <LevelBadge level={targetLevel} />
        </div>

        <button
          onClick={handleEnforce}
          disabled={loading}
          className="px-4 py-2 font-theme-data text-sm border border-[var(--acid-green)] text-[var(--acid-green)] hover:bg-[var(--acid-green)]/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {loading ? '[ENFORCING...]' : '[CHECK ACCESS]'}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-400 font-theme-data text-sm">
          {error}
        </div>
      )}

      {/* Result */}
      {result && (
        <div
          className={`p-4 border ${
            result.allowed
              ? 'bg-[var(--acid-green)]/5 border-[var(--acid-green)]/30'
              : 'bg-red-500/5 border-red-500/30'
          }`}
        >
          <div className="flex items-center gap-3 mb-4">
            <span
              className={`text-xl font-theme-data ${result.allowed ? 'text-[var(--acid-green)]' : 'text-red-400'}`}
            >
              {result.allowed ? '[ACCESS GRANTED]' : '[ACCESS DENIED]'}
            </span>
          </div>

          {/* Flow visualization */}
          <div className="flex items-center gap-3 mb-4 text-xs font-theme-data">
            <LevelBadge level={result.source_classification} />
            <span className={result.allowed ? 'text-[var(--acid-green)]' : 'text-red-400'}>
              {result.allowed ? '==>' : '=X='}
            </span>
            <LevelBadge level={result.target_classification} />
            <span className="text-[var(--text-muted)]">({result.operation})</span>
          </div>

          {/* Violations */}
          {result.violations && result.violations.length > 0 && (
            <div>
              <span className="text-[10px] font-theme-data text-red-400 uppercase">
                Policy Violations:
              </span>
              <ul className="mt-1 space-y-1">
                {result.violations.map((v, i) => (
                  <li
                    key={i}
                    className="text-xs font-theme-data text-red-400 flex items-start gap-2"
                  >
                    <span className="text-red-400/50">!</span> {v}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* No violations */}
          {result.allowed && (!result.violations || result.violations.length === 0) && (
            <p className="text-xs font-theme-data text-[var(--acid-green)]">
              All policy requirements satisfied. Cross-context access is permitted.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
