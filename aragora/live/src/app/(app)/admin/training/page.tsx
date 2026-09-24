'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';
import { useAragoraClient, useClientAuth } from '@/hooks/useAragoraClient';
import type {
  TrainingStatsResponse,
  TrainingExportResponse,
  AragoraError,
} from '@/lib/aragora-client';

type ExportTab = 'sft' | 'dpo' | 'gauntlet';
type ExportFormat = 'json' | 'jsonl';

interface ExportOptions {
  sft: {
    min_confidence: number;
    min_success_rate: number;
    limit: number;
    include_critiques: boolean;
    include_patterns: boolean;
    include_debates: boolean;
  };
  dpo: { min_confidence_diff: number; limit: number };
  gauntlet: { persona: 'gdpr' | 'hipaa' | 'ai_act' | 'all'; min_severity: number; limit: number };
}

function StatCard({
  label,
  value,
  color = 'acid-green',
}: {
  label: string;
  value: number | string;
  color?: string;
}) {
  return (
    <div className="card p-4">
      <div className="font-theme-data text-xs text-text-muted mb-1">{label}</div>
      <div className={`font-theme-data text-2xl text-${color}`}>{value}</div>
    </div>
  );
}

function ExportButton({
  onClick,
  loading,
  disabled,
  children,
}: {
  onClick: () => void;
  loading: boolean;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={loading || disabled}
      className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {loading ? 'Exporting...' : children}
    </button>
  );
}

function OptionSlider({
  label,
  value,
  onChange,
  min,
  max,
  step = 0.1,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
}) {
  return (
    <div className="space-y-1">
      <div className="flex justify-between">
        <label className="font-theme-data text-xs text-text-muted">{label}</label>
        <span className="font-theme-data text-xs text-[var(--acid-cyan)]">{value.toFixed(2)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-2 bg-surface rounded-lg appearance-none cursor-pointer accent-acid-green"
      />
    </div>
  );
}

function OptionCheckbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="w-4 h-4 accent-acid-green"
      />
      <span className="font-theme-data text-xs text-text">{label}</span>
    </label>
  );
}

export default function TrainingExportPage() {
  const client = useAragoraClient();
  const { isAuthenticated } = useAuth();
  const { isAdmin } = useClientAuth();

  const [stats, setStats] = useState<TrainingStatsResponse['stats'] | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportResult, setExportResult] = useState<TrainingExportResponse | null>(null);
  const [activeTab, setActiveTab] = useState<ExportTab>('sft');
  const [format, setFormat] = useState<ExportFormat>('jsonl');

  const [options, setOptions] = useState<ExportOptions>({
    sft: {
      min_confidence: 0.7,
      min_success_rate: 0.6,
      limit: 1000,
      include_critiques: true,
      include_patterns: true,
      include_debates: true,
    },
    dpo: { min_confidence_diff: 0.1, limit: 500 },
    gauntlet: { persona: 'all', min_severity: 0.5, limit: 500 },
  });

  const fetchStats = useCallback(async () => {
    if (!isAuthenticated) return;

    try {
      setLoading(true);
      setError(null);
      const response = await client.training.stats();
      setStats(response.stats);
    } catch (err) {
      if (err && typeof err === 'object' && 'toUserMessage' in err) {
        setError((err as AragoraError).toUserMessage());
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Failed to fetch training stats');
      }
    } finally {
      setLoading(false);
    }
  }, [client, isAuthenticated]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchStats();
    }
  }, [fetchStats, isAuthenticated]);

  const handleExport = async () => {
    setExporting(true);
    setError(null);
    setExportResult(null);

    try {
      let result: TrainingExportResponse;

      switch (activeTab) {
        case 'sft':
          result = await client.training.exportSFT({ ...options.sft, format });
          break;
        case 'dpo':
          result = await client.training.exportDPO({ ...options.dpo, format });
          break;
        case 'gauntlet':
          result = await client.training.exportGauntlet({ ...options.gauntlet, format });
          break;
      }

      setExportResult(result);

      // Trigger download
      const blob = new Blob(
        [
          format === 'jsonl'
            ? result.data.map((d) => JSON.stringify(d)).join('\n')
            : JSON.stringify(result.data, null, 2),
        ],
        { type: 'application/json' },
      );
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `aragora_${activeTab}_export_${Date.now()}.${format}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      if (err && typeof err === 'object' && 'toUserMessage' in err) {
        setError((err as AragoraError).toUserMessage());
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Export failed');
      }
    } finally {
      setExporting(false);
    }
  };

  const updateSFTOption = <K extends keyof ExportOptions['sft']>(
    key: K,
    value: ExportOptions['sft'][K],
  ) => {
    setOptions((prev) => ({ ...prev, sft: { ...prev.sft, [key]: value } }));
  };

  const updateDPOOption = <K extends keyof ExportOptions['dpo']>(
    key: K,
    value: ExportOptions['dpo'][K],
  ) => {
    setOptions((prev) => ({ ...prev, dpo: { ...prev.dpo, [key]: value } }));
  };

  const updateGauntletOption = <K extends keyof ExportOptions['gauntlet']>(
    key: K,
    value: ExportOptions['gauntlet'][K],
  ) => {
    setOptions((prev) => ({ ...prev, gauntlet: { ...prev.gauntlet, [key]: value } }));
  };

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Header */}
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <div className="flex items-center gap-4">
              <Link
                href="/admin"
                className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
              >
                [ADMIN]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        {/* Sub Navigation */}
        <div className="border-b border-[var(--accent)]/20 bg-surface/40">
          <div className="container mx-auto px-4">
            <div className="flex gap-4 overflow-x-auto">
              <Link
                href="/admin"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                SYSTEM
              </Link>
              <Link
                href="/admin/organizations"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                ORGANIZATIONS
              </Link>
              <Link
                href="/admin/users"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                USERS
              </Link>
              <Link
                href="/admin/personas"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                PERSONAS
              </Link>
              <Link
                href="/admin/audit"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                AUDIT
              </Link>
              <Link
                href="/admin/revenue"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                REVENUE
              </Link>
              <Link
                href="/admin/training"
                className="px-4 py-2 font-theme-data text-sm text-[var(--accent)] border-b-2 border-[var(--accent)]"
              >
                TRAINING
              </Link>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6 flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
                Training Data Export
              </h1>
              <p className="text-text-muted font-theme-data text-sm">
                Export debate data for ML model training (SFT, DPO, Gauntlet).
              </p>
            </div>
            <button
              onClick={fetchStats}
              disabled={loading}
              className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
            >
              {loading ? 'Loading...' : 'Refresh'}
            </button>
          </div>

          {!isAdmin && (
            <div className="card p-6 mb-6 border-acid-yellow/40">
              <div className="flex items-center gap-2 text-[var(--acid-yellow)] font-theme-data text-sm">
                <span>!</span>
                <span>Admin access required. Training exports need elevated permissions.</span>
              </div>
            </div>
          )}

          {error && (
            <div className="card p-4 mb-6 border-acid-red/40 bg-acid-red/10">
              <p className="text-acid-red font-theme-data text-sm">{error}</p>
            </div>
          )}

          {loading ? (
            <div className="card p-8 text-center">
              <div className="font-theme-data text-text-muted animate-pulse">
                Loading training stats...
              </div>
            </div>
          ) : (
            stats && (
              <>
                {/* Stats Overview */}
                <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
                  <StatCard
                    label="SFT Records"
                    value={stats.sft_available.toLocaleString()}
                    color="acid-green"
                  />
                  <StatCard
                    label="DPO Pairs"
                    value={stats.dpo_available.toLocaleString()}
                    color="acid-cyan"
                  />
                  <StatCard
                    label="Gauntlet Findings"
                    value={stats.gauntlet_available.toLocaleString()}
                    color="acid-yellow"
                  />
                  <StatCard
                    label="Total Debates"
                    value={stats.total_debates.toLocaleString()}
                    color="acid-magenta"
                  />
                  <StatCard
                    label="With Consensus"
                    value={stats.debates_with_consensus.toLocaleString()}
                    color="text"
                  />
                </div>

                {/* Export Tabs */}
                <div className="card p-6 mb-6">
                  <div className="flex gap-4 mb-6 border-b border-[var(--accent)]/20 pb-4">
                    {(['sft', 'dpo', 'gauntlet'] as ExportTab[]).map((tab) => (
                      <button
                        key={tab}
                        onClick={() => setActiveTab(tab)}
                        className={`px-4 py-2 font-theme-data text-sm rounded transition-colors ${
                          activeTab === tab
                            ? 'bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/40'
                            : 'text-text-muted hover:text-text'
                        }`}
                      >
                        {tab.toUpperCase()}
                      </button>
                    ))}
                  </div>

                  {/* SFT Options */}
                  {activeTab === 'sft' && (
                    <div className="space-y-6">
                      <div>
                        <h3 className="font-theme-data text-[var(--accent)] mb-4">
                          SFT Export Options
                        </h3>
                        <p className="font-theme-data text-xs text-text-muted mb-4">
                          Supervised Fine-Tuning data from high-quality debate conclusions.
                        </p>
                      </div>
                      <div className="grid md:grid-cols-2 gap-6">
                        <div className="space-y-4">
                          <OptionSlider
                            label="Min Confidence"
                            value={options.sft.min_confidence}
                            onChange={(v) => updateSFTOption('min_confidence', v)}
                            min={0}
                            max={1}
                          />
                          <OptionSlider
                            label="Min Success Rate"
                            value={options.sft.min_success_rate}
                            onChange={(v) => updateSFTOption('min_success_rate', v)}
                            min={0}
                            max={1}
                          />
                          <OptionSlider
                            label="Max Records"
                            value={options.sft.limit}
                            onChange={(v) => updateSFTOption('limit', Math.round(v))}
                            min={100}
                            max={10000}
                            step={100}
                          />
                        </div>
                        <div className="space-y-3">
                          <OptionCheckbox
                            label="Include critiques"
                            checked={options.sft.include_critiques}
                            onChange={(v) => updateSFTOption('include_critiques', v)}
                          />
                          <OptionCheckbox
                            label="Include patterns"
                            checked={options.sft.include_patterns}
                            onChange={(v) => updateSFTOption('include_patterns', v)}
                          />
                          <OptionCheckbox
                            label="Include full debates"
                            checked={options.sft.include_debates}
                            onChange={(v) => updateSFTOption('include_debates', v)}
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  {/* DPO Options */}
                  {activeTab === 'dpo' && (
                    <div className="space-y-6">
                      <div>
                        <h3 className="font-theme-data text-[var(--accent)] mb-4">
                          DPO Export Options
                        </h3>
                        <p className="font-theme-data text-xs text-text-muted mb-4">
                          Direct Preference Optimization pairs from agent comparisons.
                        </p>
                      </div>
                      <div className="max-w-md space-y-4">
                        <OptionSlider
                          label="Min Confidence Difference"
                          value={options.dpo.min_confidence_diff}
                          onChange={(v) => updateDPOOption('min_confidence_diff', v)}
                          min={0}
                          max={1}
                        />
                        <OptionSlider
                          label="Max Records"
                          value={options.dpo.limit}
                          onChange={(v) => updateDPOOption('limit', Math.round(v))}
                          min={100}
                          max={5000}
                          step={100}
                        />
                      </div>
                    </div>
                  )}

                  {/* Gauntlet Options */}
                  {activeTab === 'gauntlet' && (
                    <div className="space-y-6">
                      <div>
                        <h3 className="font-theme-data text-[var(--accent)] mb-4">
                          Gauntlet Export Options
                        </h3>
                        <p className="font-theme-data text-xs text-text-muted mb-4">
                          Adversarial findings from compliance gauntlet tests.
                        </p>
                      </div>
                      <div className="max-w-md space-y-4">
                        <div className="space-y-2">
                          <label
                            htmlFor="compliance-persona"
                            className="font-theme-data text-xs text-text-muted"
                          >
                            Compliance Persona
                          </label>
                          <select
                            id="compliance-persona"
                            value={options.gauntlet.persona}
                            onChange={(e) =>
                              updateGauntletOption(
                                'persona',
                                e.target.value as typeof options.gauntlet.persona,
                              )
                            }
                            aria-label="Select compliance persona"
                            className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm text-text"
                          >
                            <option value="all">All Personas</option>
                            <option value="gdpr">GDPR</option>
                            <option value="hipaa">HIPAA</option>
                            <option value="ai_act">AI Act</option>
                          </select>
                        </div>
                        <OptionSlider
                          label="Min Severity"
                          value={options.gauntlet.min_severity}
                          onChange={(v) => updateGauntletOption('min_severity', v)}
                          min={0}
                          max={1}
                        />
                        <OptionSlider
                          label="Max Records"
                          value={options.gauntlet.limit}
                          onChange={(v) => updateGauntletOption('limit', Math.round(v))}
                          min={100}
                          max={5000}
                          step={100}
                        />
                      </div>
                    </div>
                  )}

                  {/* Export Controls */}
                  <div className="mt-6 pt-6 border-t border-[var(--accent)]/20 flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      <label
                        htmlFor="export-format"
                        className="font-theme-data text-xs text-text-muted"
                      >
                        Format:
                      </label>
                      <select
                        id="export-format"
                        value={format}
                        onChange={(e) => setFormat(e.target.value as ExportFormat)}
                        aria-label="Select export format"
                        className="p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm text-text"
                      >
                        <option value="jsonl">JSONL (line-delimited)</option>
                        <option value="json">JSON (array)</option>
                      </select>
                    </div>
                    <ExportButton onClick={handleExport} loading={exporting} disabled={!isAdmin}>
                      Export {activeTab.toUpperCase()} Data
                    </ExportButton>
                  </div>
                </div>

                {/* Export Result */}
                {exportResult && (
                  <div className="card p-6 border-[var(--accent)]/40">
                    <h3 className="font-theme-data text-[var(--accent)] mb-4">Export Complete</h3>
                    <div className="grid md:grid-cols-3 gap-4">
                      <div>
                        <div className="font-theme-data text-xs text-text-muted">
                          Records Exported
                        </div>
                        <div className="font-theme-data text-xl text-[var(--acid-cyan)]">
                          {exportResult.total.toLocaleString()}
                        </div>
                      </div>
                      <div>
                        <div className="font-theme-data text-xs text-text-muted">Format</div>
                        <div className="font-theme-data text-xl text-text">
                          {exportResult.format.toUpperCase()}
                        </div>
                      </div>
                      <div>
                        <div className="font-theme-data text-xs text-text-muted">Exported At</div>
                        <div className="font-theme-data text-sm text-text">
                          {new Date(exportResult.exported_at).toLocaleString()}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Format Info */}
                <div className="mt-6 card p-4 bg-surface/50">
                  <h4 className="font-theme-data text-xs text-text-muted mb-2">
                    Format Documentation
                  </h4>
                  <div className="font-theme-data text-xs text-text space-y-1">
                    <p>
                      <span className="text-[var(--accent)]">SFT:</span> Task-response pairs for
                      instruction fine-tuning
                    </p>
                    <p>
                      <span className="text-[var(--acid-cyan)]">DPO:</span> Chosen/rejected pairs
                      for preference learning
                    </p>
                    <p>
                      <span className="text-[var(--acid-yellow)]">Gauntlet:</span> Adversarial
                      findings for safety training
                    </p>
                  </div>
                </div>
              </>
            )
          )}
        </div>
      </main>
    </>
  );
}
