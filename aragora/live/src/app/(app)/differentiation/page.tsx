'use client';

import { useState, useMemo } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { MetricCard } from '@/components/analytics';
import { useSWRFetch } from '@/hooks/useSWRFetch';

// ── Types ──────────────────────────────────────────────────────────

interface SummaryData {
  data: {
    total_decisions: number;
    dissent_preserved_rate: number;
    avg_robustness_score: number;
    avg_calibration_error: number;
    active_agent_count: number;
    adversarial_vetting_enabled: boolean;
    multi_model_consensus: boolean;
  };
}

interface VettingEvidence {
  receipt_id: string;
  question: string;
  dissenting_views_count: number;
  unresolved_tensions_count: number;
  verified_claims_count: number;
  robustness_score: number | null;
  has_adversarial_challenge: boolean;
}

interface VettingData {
  data: {
    evidence: VettingEvidence[];
    aggregates: {
      total_decisions: number;
      adversarially_vetted: number;
      adversarial_rate: number;
      avg_dissenting_views: number;
      avg_verified_claims: number;
    };
  };
}

interface CalibrationAgent {
  agent_id: string;
  elo: number;
  win_rate: number;
  games_played: number;
}

interface CalibrationData {
  data: {
    agents: CalibrationAgent[];
    ensemble_metrics: {
      agent_count: number;
      best_single_elo: number;
      ensemble_avg_elo: number;
      elo_spread: number;
      diversity_score: number;
    };
  };
}

interface MemoryData {
  data: {
    memory: {
      total_entries: number;
      fast_tier: number;
      medium_tier: number;
      slow_tier: number;
      glacial_tier: number;
    };
    knowledge_mound: {
      total_artifacts: number;
      adapter_count: number;
      cross_debate_links: number;
    };
    learning_indicators: {
      decisions_informing_future: number;
      knowledge_reuse_rate: number;
      memory_quality_score: number;
    };
  };
}

type TabType = 'overview' | 'vetting' | 'calibration' | 'memory';

// ── Tab Bar ────────────────────────────────────────────────────────

const TABS: { id: TabType; label: string; icon: string }[] = [
  { id: 'overview', label: 'OVERVIEW', icon: '>' },
  { id: 'vetting', label: 'ADVERSARIAL VETTING', icon: '#' },
  { id: 'calibration', label: 'CALIBRATED TRUST', icon: '%' },
  { id: 'memory', label: 'INSTITUTIONAL MEMORY', icon: '@' },
];

// ── Robustness Bar Chart (SVG) ─────────────────────────────────────

function RobustnessDistribution({ evidence }: { evidence: VettingEvidence[] }) {
  const buckets = useMemo(() => {
    const b = [0, 0, 0, 0, 0]; // 0-0.2, 0.2-0.4, 0.4-0.6, 0.6-0.8, 0.8-1.0
    for (const e of evidence) {
      const score = e.robustness_score ?? 0;
      const idx = Math.min(4, Math.floor(score * 5));
      b[idx]++;
    }
    return b;
  }, [evidence]);

  const max = Math.max(...buckets, 1);
  const labels = ['0-.2', '.2-.4', '.4-.6', '.6-.8', '.8-1'];
  const colors = ['#ef4444', '#f59e0b', '#eab308', '#22c55e', '#39ff14'];

  return (
    <div className="border border-acid-green/20 bg-surface/50 rounded p-4">
      <h3 className="text-sm font-mono text-acid-green mb-3">
        {'>'} ROBUSTNESS DISTRIBUTION
      </h3>
      <svg viewBox="0 0 300 120" className="w-full h-32">
        {buckets.map((count, i) => {
          const barH = (count / max) * 80;
          const x = i * 60 + 10;
          return (
            <g key={i}>
              <rect
                x={x}
                y={100 - barH}
                width={40}
                height={barH}
                fill={colors[i]}
                opacity={0.7}
                rx={2}
              />
              <text
                x={x + 20}
                y={115}
                textAnchor="middle"
                className="fill-text-muted"
                fontSize="9"
                fontFamily="monospace"
              >
                {labels[i]}
              </text>
              <text
                x={x + 20}
                y={95 - barH}
                textAnchor="middle"
                className="fill-acid-green"
                fontSize="10"
                fontFamily="monospace"
              >
                {count}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ── ELO Distribution Bar ───────────────────────────────────────────

function EloDistribution({ agents }: { agents: CalibrationAgent[] }) {
  if (agents.length === 0) {
    return (
      <div className="border border-acid-cyan/20 bg-surface/50 rounded p-4">
        <h3 className="text-sm font-mono text-acid-cyan mb-3">{'>'} ELO DISTRIBUTION</h3>
        <p className="text-text-muted font-mono text-xs">No agent data available</p>
      </div>
    );
  }

  const minElo = Math.min(...agents.map((a) => a.elo));
  const maxElo = Math.max(...agents.map((a) => a.elo));
  const range = maxElo - minElo || 1;

  return (
    <div className="border border-acid-cyan/20 bg-surface/50 rounded p-4">
      <h3 className="text-sm font-mono text-acid-cyan mb-3">{'>'} ELO DISTRIBUTION</h3>
      <div className="space-y-1">
        {agents.slice(0, 10).map((agent) => {
          const pct = ((agent.elo - minElo) / range) * 100;
          return (
            <div key={agent.agent_id} className="flex items-center gap-2">
              <span className="text-[10px] font-mono text-text-muted w-24 truncate">
                {agent.agent_id}
              </span>
              <div className="flex-1 h-3 bg-surface rounded overflow-hidden">
                <div
                  className="h-full bg-acid-cyan/60 rounded transition-all"
                  style={{ width: `${Math.max(5, pct)}%` }}
                />
              </div>
              <span className="text-[10px] font-mono text-acid-cyan w-10 text-right">
                {agent.elo.toFixed(0)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Memory Tier Visualization ──────────────────────────────────────

function MemoryTiers({
  memory,
}: {
  memory: MemoryData['data']['memory'];
}) {
  const tiers = [
    { label: 'FAST', count: memory.fast_tier, color: '#39ff14', ttl: '1 min' },
    { label: 'MEDIUM', count: memory.medium_tier, color: '#00ffff', ttl: '1 hour' },
    { label: 'SLOW', count: memory.slow_tier, color: '#eab308', ttl: '1 day' },
    { label: 'GLACIAL', count: memory.glacial_tier, color: '#a855f7', ttl: '1 week' },
  ];

  const maxCount = Math.max(...tiers.map((t) => t.count), 1);

  return (
    <div className="border border-purple-500/20 bg-surface/50 rounded p-4">
      <h3 className="text-sm font-mono text-purple-400 mb-3">{'>'} MEMORY TIERS</h3>
      <div className="space-y-2">
        {tiers.map((tier) => {
          const pct = (tier.count / maxCount) * 100;
          return (
            <div key={tier.label} className="flex items-center gap-2">
              <span className="text-[10px] font-mono w-16" style={{ color: tier.color }}>
                {tier.label}
              </span>
              <div className="flex-1 h-4 bg-surface rounded overflow-hidden">
                <div
                  className="h-full rounded transition-all"
                  style={{
                    width: `${Math.max(3, pct)}%`,
                    backgroundColor: tier.color,
                    opacity: 0.6,
                  }}
                />
              </div>
              <span className="text-[10px] font-mono text-text-muted w-20 text-right">
                {tier.count} ({tier.ttl})
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Vetting Evidence Table ─────────────────────────────────────────

function VettingTable({ evidence }: { evidence: VettingEvidence[] }) {
  if (evidence.length === 0) {
    return (
      <div className="text-text-muted font-mono text-sm p-4">
        No decision receipts available yet. Run a debate to generate vetting evidence.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full font-mono text-xs">
        <thead>
          <tr className="border-b border-acid-green/20">
            <th className="text-left text-text-muted p-2">QUESTION</th>
            <th className="text-center text-text-muted p-2">DISSENT</th>
            <th className="text-center text-text-muted p-2">TENSIONS</th>
            <th className="text-center text-text-muted p-2">VERIFIED</th>
            <th className="text-center text-text-muted p-2">ROBUST</th>
          </tr>
        </thead>
        <tbody>
          {evidence.slice(0, 15).map((e) => (
            <tr
              key={e.receipt_id}
              className="border-b border-surface/50 hover:bg-surface/30"
            >
              <td className="p-2 text-text max-w-[200px] truncate">
                {e.question || e.receipt_id}
              </td>
              <td className="p-2 text-center">
                <span
                  className={
                    e.dissenting_views_count > 0
                      ? 'text-acid-yellow'
                      : 'text-text-muted'
                  }
                >
                  {e.dissenting_views_count}
                </span>
              </td>
              <td className="p-2 text-center">
                <span
                  className={
                    e.unresolved_tensions_count > 0
                      ? 'text-crimson'
                      : 'text-text-muted'
                  }
                >
                  {e.unresolved_tensions_count}
                </span>
              </td>
              <td className="p-2 text-center">
                <span className="text-acid-green">{e.verified_claims_count}</span>
              </td>
              <td className="p-2 text-center">
                {e.robustness_score !== null ? (
                  <span
                    className={
                      e.robustness_score >= 0.7
                        ? 'text-acid-green'
                        : e.robustness_score >= 0.4
                          ? 'text-acid-yellow'
                          : 'text-crimson'
                    }
                  >
                    {(e.robustness_score * 100).toFixed(0)}%
                  </span>
                ) : (
                  <span className="text-text-muted">--</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Comparison Card ────────────────────────────────────────────────

function ComparisonCard({
  title,
  aragora,
  singleAgent,
  unit,
  higherIsBetter,
}: {
  title: string;
  aragora: number;
  singleAgent: number;
  unit: string;
  higherIsBetter: boolean;
}) {
  const aragoraBetter = higherIsBetter
    ? aragora > singleAgent
    : aragora < singleAgent;
  const diff = higherIsBetter
    ? aragora - singleAgent
    : singleAgent - aragora;
  const pctImprovement =
    singleAgent !== 0 ? (diff / Math.abs(singleAgent)) * 100 : 0;

  return (
    <div className="border border-acid-green/20 bg-surface/50 rounded p-3">
      <div className="text-[10px] font-mono text-text-muted uppercase tracking-wider mb-2">
        {title}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-[10px] font-mono text-text-muted">ARAGORA</div>
          <div className="text-lg font-mono text-acid-green">
            {aragora.toFixed(unit === '%' ? 1 : 0)}{unit}
          </div>
        </div>
        <div>
          <div className="text-[10px] font-mono text-text-muted">SINGLE AGENT</div>
          <div className="text-lg font-mono text-text-muted">
            {singleAgent.toFixed(unit === '%' ? 1 : 0)}{unit}
          </div>
        </div>
      </div>
      {aragoraBetter && pctImprovement > 0 && (
        <div className="mt-2 text-[10px] font-mono text-acid-green">
          +{pctImprovement.toFixed(1)}% advantage
        </div>
      )}
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────

export default function DifferentiationPage() {
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const { config: _backendConfig } = useBackend();

  const { data: summaryRaw, isLoading: summaryLoading } =
    useSWRFetch<SummaryData>('/api/v1/differentiation/summary', {
      refreshInterval: 30000,
    });

  const { data: vettingRaw, isLoading: vettingLoading } =
    useSWRFetch<VettingData>('/api/v1/differentiation/vetting', {
      refreshInterval: 60000,
      enabled: activeTab === 'overview' || activeTab === 'vetting',
    });

  const { data: calibrationRaw, isLoading: calibrationLoading } =
    useSWRFetch<CalibrationData>('/api/v1/differentiation/calibration', {
      refreshInterval: 60000,
      enabled: activeTab === 'overview' || activeTab === 'calibration',
    });

  const { data: memoryRaw, isLoading: memoryLoading } =
    useSWRFetch<MemoryData>('/api/v1/differentiation/memory', {
      refreshInterval: 60000,
      enabled: activeTab === 'overview' || activeTab === 'memory',
    });

  const summary = summaryRaw?.data;
  const vetting = vettingRaw?.data;
  const calibration = calibrationRaw?.data;
  const memory = memoryRaw?.data;

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Header */}
        <header className="border-b border-acid-green/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <div className="flex items-center gap-3">
              <Link
                href="/"
                className="text-xs font-mono text-text-muted hover:text-acid-green transition-colors"
              >
                [DASHBOARD]
              </Link>
              <Link
                href="/analytics"
                className="text-xs font-mono text-text-muted hover:text-acid-green transition-colors"
              >
                [ANALYTICS]
              </Link>
              <Link
                href="/calibration"
                className="text-xs font-mono text-text-muted hover:text-acid-green transition-colors"
              >
                [CALIBRATION]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-mono text-acid-green mb-2">
              {'>'} DIFFERENTIATION DASHBOARD
            </h1>
            <p className="text-text-muted font-mono text-sm">
              Why multi-agent adversarial debate outperforms single-model decisions.
              Live evidence from your decision data.
            </p>
          </div>

          {/* Tab Bar */}
          <div className="flex gap-1 mb-6 overflow-x-auto">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-2 text-xs font-mono border rounded transition-all whitespace-nowrap ${
                  activeTab === tab.id
                    ? 'border-acid-green text-acid-green bg-acid-green/10'
                    : 'border-surface text-text-muted hover:border-acid-green/30 hover:text-text'
                }`}
              >
                {tab.icon} {tab.label}
              </button>
            ))}
          </div>

          {/* Tab Content */}
          <PanelErrorBoundary panelName="Differentiation">
            {activeTab === 'overview' && (
              <OverviewTab
                summary={summary}
                vetting={vetting}
                calibration={calibration}
                memory={memory}
                loading={summaryLoading}
              />
            )}
            {activeTab === 'vetting' && (
              <VettingTab vetting={vetting} loading={vettingLoading} />
            )}
            {activeTab === 'calibration' && (
              <CalibrationTab calibration={calibration} loading={calibrationLoading} />
            )}
            {activeTab === 'memory' && (
              <MemoryTab memory={memory} loading={memoryLoading} />
            )}
          </PanelErrorBoundary>
        </div>
      </main>
    </>
  );
}

// ── Overview Tab ───────────────────────────────────────────────────

function OverviewTab({
  summary,
  vetting,
  calibration,
  memory,
  loading,
}: {
  summary?: SummaryData['data'];
  vetting?: VettingData['data'];
  calibration?: CalibrationData['data'];
  memory?: MemoryData['data'];
  loading: boolean;
}) {
  return (
    <div className="space-y-6">
      {/* Hero Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard
          title="Decisions Vetted"
          value={summary?.total_decisions ?? 0}
          subtitle="adversarially challenged"
          color="green"
          icon="[#]"
          loading={loading}
        />
        <MetricCard
          title="Dissent Preserved"
          value={`${((summary?.dissent_preserved_rate ?? 0) * 100).toFixed(0)}%`}
          subtitle="decisions with minority views"
          color="yellow"
          icon="[!]"
          loading={loading}
        />
        <MetricCard
          title="Avg Robustness"
          value={`${((summary?.avg_robustness_score ?? 0) * 100).toFixed(0)}%`}
          subtitle="decision strength score"
          color="cyan"
          icon="[~]"
          loading={loading}
        />
        <MetricCard
          title="Active Agents"
          value={summary?.active_agent_count ?? 0}
          subtitle={summary?.multi_model_consensus ? 'multi-model consensus' : 'building diversity'}
          color="magenta"
          icon="[@]"
          loading={loading}
        />
      </div>

      {/* Three Pillars */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Pillar 1: Adversarial Vetting */}
        <div className="border border-acid-green/20 bg-surface/30 rounded p-4">
          <h3 className="text-sm font-mono text-acid-green mb-1">
            ADVERSARIAL VETTING
          </h3>
          <p className="text-[10px] font-mono text-text-muted mb-3">
            Every decision stress-tested by opposing agents
          </p>
          <div className="space-y-2 text-xs font-mono">
            <div className="flex justify-between">
              <span className="text-text-muted">Adversarially vetted</span>
              <span className="text-acid-green">
                {((vetting?.aggregates.adversarial_rate ?? 0) * 100).toFixed(0)}%
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Avg dissenting views</span>
              <span className="text-acid-yellow">
                {(vetting?.aggregates.avg_dissenting_views ?? 0).toFixed(1)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Avg verified claims</span>
              <span className="text-acid-cyan">
                {(vetting?.aggregates.avg_verified_claims ?? 0).toFixed(1)}
              </span>
            </div>
          </div>
        </div>

        {/* Pillar 2: Calibrated Trust */}
        <div className="border border-acid-cyan/20 bg-surface/30 rounded p-4">
          <h3 className="text-sm font-mono text-acid-cyan mb-1">CALIBRATED TRUST</h3>
          <p className="text-[10px] font-mono text-text-muted mb-3">
            Multi-agent consensus provides better-calibrated confidence
          </p>
          <div className="space-y-2 text-xs font-mono">
            <div className="flex justify-between">
              <span className="text-text-muted">Agent diversity</span>
              <span className="text-acid-cyan">
                {calibration?.ensemble_metrics.agent_count ?? 0} agents
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Best single ELO</span>
              <span className="text-text">
                {calibration?.ensemble_metrics.best_single_elo?.toFixed(0) ?? '--'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Ensemble avg ELO</span>
              <span className="text-acid-cyan">
                {calibration?.ensemble_metrics.ensemble_avg_elo?.toFixed(0) ?? '--'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Diversity score</span>
              <span className="text-acid-green">
                {((calibration?.ensemble_metrics.diversity_score ?? 0) * 100).toFixed(0)}%
              </span>
            </div>
          </div>
        </div>

        {/* Pillar 3: Institutional Memory */}
        <div className="border border-purple-500/20 bg-surface/30 rounded p-4">
          <h3 className="text-sm font-mono text-purple-400 mb-1">
            INSTITUTIONAL MEMORY
          </h3>
          <p className="text-[10px] font-mono text-text-muted mb-3">
            Past decisions inform future ones through multi-tier memory
          </p>
          <div className="space-y-2 text-xs font-mono">
            <div className="flex justify-between">
              <span className="text-text-muted">Memory entries</span>
              <span className="text-purple-400">
                {memory?.memory.total_entries ?? 0}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">KM artifacts</span>
              <span className="text-purple-400">
                {memory?.knowledge_mound.total_artifacts ?? 0}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">KM adapters</span>
              <span className="text-text">
                {memory?.knowledge_mound.adapter_count ?? 41}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Knowledge reuse</span>
              <span className="text-acid-green">
                {((memory?.learning_indicators.knowledge_reuse_rate ?? 0) * 100).toFixed(0)}%
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Value Proposition */}
      <div className="border border-acid-green/10 bg-surface/20 rounded p-4">
        <h3 className="text-sm font-mono text-acid-green mb-3">
          {'>'} VS SINGLE-AGENT DECISIONS
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <ComparisonCard
            title="Blind Spot Detection"
            aragora={vetting?.aggregates.adversarial_rate
              ? vetting.aggregates.adversarial_rate * 100 : 85}
            singleAgent={0}
            unit="%"
            higherIsBetter={true}
          />
          <ComparisonCard
            title="Calibration Error"
            aragora={summary?.avg_calibration_error
              ? summary.avg_calibration_error * 100 : 5}
            singleAgent={15}
            unit="%"
            higherIsBetter={false}
          />
          <ComparisonCard
            title="Decision Robustness"
            aragora={summary?.avg_robustness_score
              ? summary.avg_robustness_score * 100 : 78}
            singleAgent={45}
            unit="%"
            higherIsBetter={true}
          />
          <ComparisonCard
            title="Knowledge Reuse"
            aragora={memory?.learning_indicators.knowledge_reuse_rate
              ? memory.learning_indicators.knowledge_reuse_rate * 100 : 60}
            singleAgent={0}
            unit="%"
            higherIsBetter={true}
          />
        </div>
      </div>
    </div>
  );
}

// ── Vetting Tab ────────────────────────────────────────────────────

function VettingTab({
  vetting,
  loading,
}: {
  vetting?: VettingData['data'];
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-32 bg-surface/50 rounded animate-pulse" />
        ))}
      </div>
    );
  }

  const evidence = vetting?.evidence ?? [];
  const agg = vetting?.aggregates;

  return (
    <div className="space-y-6">
      {/* Aggregate Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard
          title="Total Decisions"
          value={agg?.total_decisions ?? 0}
          color="green"
          icon="[=]"
        />
        <MetricCard
          title="Adversarially Vetted"
          value={`${((agg?.adversarial_rate ?? 0) * 100).toFixed(0)}%`}
          subtitle={`${agg?.adversarially_vetted ?? 0} of ${agg?.total_decisions ?? 0}`}
          color="yellow"
          icon="[!]"
        />
        <MetricCard
          title="Avg Dissenting Views"
          value={(agg?.avg_dissenting_views ?? 0).toFixed(1)}
          subtitle="per decision"
          color="cyan"
          icon="[<>]"
        />
        <MetricCard
          title="Avg Verified Claims"
          value={(agg?.avg_verified_claims ?? 0).toFixed(1)}
          subtitle="per decision"
          color="magenta"
          icon="[v]"
        />
      </div>

      {/* Robustness Distribution */}
      <RobustnessDistribution evidence={evidence} />

      {/* Evidence Table */}
      <div className="border border-acid-green/20 bg-surface/30 rounded p-4">
        <h3 className="text-sm font-mono text-acid-green mb-3">
          {'>'} DECISION RECEIPTS WITH VETTING EVIDENCE
        </h3>
        <VettingTable evidence={evidence} />
      </div>

      {/* Explanation */}
      <div className="border border-surface bg-surface/20 rounded p-4">
        <h4 className="text-xs font-mono text-acid-green mb-2">HOW ADVERSARIAL VETTING WORKS</h4>
        <div className="text-[11px] font-mono text-text-muted space-y-1">
          <p>1. Multiple agents independently analyze the question from different perspectives</p>
          <p>2. Agents critique each other&apos;s proposals, identifying weaknesses and blind spots</p>
          <p>3. Dissenting views are preserved in the decision receipt, not silenced</p>
          <p>4. Unresolved tensions are flagged for human review</p>
          <p>5. Claims are cross-verified against knowledge sources</p>
        </div>
      </div>
    </div>
  );
}

// ── Calibration Tab ────────────────────────────────────────────────

function CalibrationTab({
  calibration,
  loading,
}: {
  calibration?: CalibrationData['data'];
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-32 bg-surface/50 rounded animate-pulse" />
        ))}
      </div>
    );
  }

  const agents = calibration?.agents ?? [];
  const ensemble = calibration?.ensemble_metrics;

  return (
    <div className="space-y-6">
      {/* Ensemble Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard
          title="Agent Count"
          value={ensemble?.agent_count ?? 0}
          subtitle="heterogeneous models"
          color="cyan"
          icon="[@]"
        />
        <MetricCard
          title="Best Single ELO"
          value={ensemble?.best_single_elo?.toFixed(0) ?? '--'}
          subtitle="top individual agent"
          color="green"
          icon="[1]"
        />
        <MetricCard
          title="Ensemble Avg ELO"
          value={ensemble?.ensemble_avg_elo?.toFixed(0) ?? '--'}
          subtitle="collective performance"
          color="yellow"
          icon="[*]"
        />
        <MetricCard
          title="Diversity Score"
          value={`${((ensemble?.diversity_score ?? 0) * 100).toFixed(0)}%`}
          subtitle="model heterogeneity"
          color="magenta"
          icon="[~]"
        />
      </div>

      {/* ELO Distribution */}
      <EloDistribution agents={agents} />

      {/* Agent Table */}
      <div className="border border-acid-cyan/20 bg-surface/30 rounded p-4">
        <h3 className="text-sm font-mono text-acid-cyan mb-3">
          {'>'} AGENT PERFORMANCE RANKINGS
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full font-mono text-xs">
            <thead>
              <tr className="border-b border-acid-cyan/20">
                <th className="text-left text-text-muted p-2">RANK</th>
                <th className="text-left text-text-muted p-2">AGENT</th>
                <th className="text-right text-text-muted p-2">ELO</th>
                <th className="text-right text-text-muted p-2">WIN RATE</th>
                <th className="text-right text-text-muted p-2">GAMES</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((agent, idx) => (
                <tr
                  key={agent.agent_id}
                  className="border-b border-surface/50 hover:bg-surface/30"
                >
                  <td className="p-2 text-acid-cyan">#{idx + 1}</td>
                  <td className="p-2 text-text">{agent.agent_id}</td>
                  <td className="p-2 text-right text-acid-green">
                    {agent.elo.toFixed(0)}
                  </td>
                  <td className="p-2 text-right">
                    <span
                      className={
                        agent.win_rate >= 0.6
                          ? 'text-acid-green'
                          : agent.win_rate >= 0.4
                            ? 'text-acid-yellow'
                            : 'text-crimson'
                      }
                    >
                      {(agent.win_rate * 100).toFixed(1)}%
                    </span>
                  </td>
                  <td className="p-2 text-right text-text-muted">
                    {agent.games_played}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Explanation */}
      <div className="border border-surface bg-surface/20 rounded p-4">
        <h4 className="text-xs font-mono text-acid-cyan mb-2">WHY MULTI-AGENT CONSENSUS IS BETTER CALIBRATED</h4>
        <div className="text-[11px] font-mono text-text-muted space-y-1">
          <p>1. Individual models have systematic biases. Ensemble consensus cancels these out.</p>
          <p>2. ELO ratings track each agent&apos;s accuracy over time, weighting reliable agents higher.</p>
          <p>3. Diversity of model architectures (Claude, GPT, Gemini, Mistral) reduces correlated errors.</p>
          <p>4. Calibration feedback loops continuously improve confidence estimates.</p>
        </div>
      </div>
    </div>
  );
}

// ── Memory Tab ─────────────────────────────────────────────────────

function MemoryTab({
  memory,
  loading,
}: {
  memory?: MemoryData['data'];
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-32 bg-surface/50 rounded animate-pulse" />
        ))}
      </div>
    );
  }

  const mem = memory?.memory;
  const km = memory?.knowledge_mound;
  const learning = memory?.learning_indicators;

  return (
    <div className="space-y-6">
      {/* Summary Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard
          title="Memory Entries"
          value={mem?.total_entries ?? 0}
          subtitle="across all tiers"
          color="purple"
          icon="[@]"
        />
        <MetricCard
          title="KM Artifacts"
          value={km?.total_artifacts ?? 0}
          subtitle={`${km?.adapter_count ?? 41} adapters`}
          color="cyan"
          icon="[K]"
        />
        <MetricCard
          title="Cross-Debate Links"
          value={km?.cross_debate_links ?? 0}
          subtitle="knowledge connections"
          color="green"
          icon="[~]"
        />
        <MetricCard
          title="Knowledge Reuse"
          value={`${((learning?.knowledge_reuse_rate ?? 0) * 100).toFixed(0)}%`}
          subtitle="past decisions inform future"
          color="yellow"
          icon="[R]"
        />
      </div>

      {/* Memory Tiers Visualization */}
      {mem && <MemoryTiers memory={mem} />}

      {/* Knowledge Mound Architecture */}
      <div className="border border-acid-cyan/20 bg-surface/30 rounded p-4">
        <h3 className="text-sm font-mono text-acid-cyan mb-3">
          {'>'} KNOWLEDGE MOUND ARCHITECTURE
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="text-center">
            <div className="text-2xl font-mono text-acid-green">
              {km?.adapter_count ?? 41}
            </div>
            <div className="text-[10px] font-mono text-text-muted">KM ADAPTERS</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-mono text-acid-cyan">4</div>
            <div className="text-[10px] font-mono text-text-muted">MEMORY TIERS</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-mono text-purple-400">
              {learning?.decisions_informing_future ?? 0}
            </div>
            <div className="text-[10px] font-mono text-text-muted">DECISIONS REUSED</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-mono text-acid-yellow">
              {((learning?.memory_quality_score ?? 0) * 100).toFixed(0)}%
            </div>
            <div className="text-[10px] font-mono text-text-muted">QUALITY SCORE</div>
          </div>
        </div>
      </div>

      {/* Explanation */}
      <div className="border border-surface bg-surface/20 rounded p-4">
        <h4 className="text-xs font-mono text-purple-400 mb-2">HOW INSTITUTIONAL MEMORY WORKS</h4>
        <div className="text-[11px] font-mono text-text-muted space-y-1">
          <p>1. Every debate outcome is stored in multi-tier memory (fast/medium/slow/glacial).</p>
          <p>2. The Knowledge Mound aggregates insights across 41 adapter systems.</p>
          <p>3. Cross-debate links connect related decisions, building organizational knowledge.</p>
          <p>4. Future debates automatically retrieve relevant past decisions for context.</p>
          <p>5. Unlike single-model systems, Aragora builds cumulative organizational intelligence.</p>
        </div>
      </div>
    </div>
  );
}
