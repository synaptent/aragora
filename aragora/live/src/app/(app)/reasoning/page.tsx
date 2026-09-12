'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

interface CruxClaim {
  claim_id?: string;
  claim: string;
  probability: number;
  sensitivity: number;
  source_agent?: string;
}

interface LoadBearingClaim {
  claim_id?: string;
  claim: string;
  centrality: number;
  source_agent?: string;
}

interface ClaimNode {
  id: string;
  text: string;
  type: string;
  agent?: string;
  evidence_count?: number;
  contradicts?: string[];
}

interface PositionRecord {
  agent: string;
  round: number;
  stance: string;
  confidence: number;
  key_argument: string;
}

interface PivotPoint {
  agent: string;
  from_round: number;
  to_round: number;
  from_stance: string;
  to_stance: string;
  pivot_magnitude: number;
  pivot_type: string;
}

interface PositionEvolution {
  debate_id: string;
  topic: string;
  positions: Record<string, PositionRecord[]>;
  pivots: PivotPoint[];
  summary: {
    convergence_score: number;
    total_pivots: number;
    reversals: number;
    stability_scores: Record<string, number>;
    influencers: Record<string, number>;
  };
}

type TabType = 'belief' | 'claims' | 'positions';

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

const STANCE_COLORS: Record<string, string> = {
  strongly_agree: '#22c55e',
  agree: '#4ade80',
  lean_agree: '#86efac',
  neutral: '#a3a3a3',
  lean_disagree: '#fca5a5',
  disagree: '#f87171',
  strongly_disagree: '#ef4444',
};

const STANCE_LABELS: Record<string, string> = {
  strongly_agree: 'STRONG YES',
  agree: 'AGREE',
  lean_agree: 'LEAN YES',
  neutral: 'NEUTRAL',
  lean_disagree: 'LEAN NO',
  disagree: 'DISAGREE',
  strongly_disagree: 'STRONG NO',
};

function stanceColor(stance: string): string {
  return STANCE_COLORS[stance] ?? '#a3a3a3';
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export default function ReasoningPage() {
  const { config } = useBackend();
  const backendUrl = config.api;

  const [activeTab, setActiveTab] = useState<TabType>('belief');
  const [debateId, setDebateId] = useState('');
  const [loadedId, setLoadedId] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Belief Network tab
  const [cruxes, setCruxes] = useState<CruxClaim[]>([]);
  const [loadBearing, setLoadBearing] = useState<LoadBearingClaim[]>([]);

  // Claims tab
  const [claims, setClaims] = useState<ClaimNode[]>([]);

  // Positions tab
  const [positions, setPositions] = useState<PositionEvolution | null>(null);

  const loadData = useCallback(async () => {
    if (!debateId.trim()) return;
    setLoading(true);
    setError(null);
    const id = encodeURIComponent(debateId.trim());

    try {
      const [cruxRes, lbRes, graphRes, posRes] = await Promise.allSettled([
        fetch(`${backendUrl}/api/belief-network/${id}/cruxes`),
        fetch(`${backendUrl}/api/belief-network/${id}/load-bearing-claims`),
        fetch(`${backendUrl}/api/belief-network/${id}/graph`),
        fetch(`${backendUrl}/api/v1/debates/${id}/positions`),
      ]);

      let anyOk = false;

      if (cruxRes.status === 'fulfilled' && cruxRes.value.ok) {
        const d = await cruxRes.value.json();
        setCruxes(d.cruxes ?? d.data?.cruxes ?? []);
        anyOk = true;
      } else {
        setCruxes([]);
      }

      if (lbRes.status === 'fulfilled' && lbRes.value.ok) {
        const d = await lbRes.value.json();
        setLoadBearing(d.load_bearing_claims ?? d.claims ?? d.data?.load_bearing_claims ?? []);
        anyOk = true;
      } else {
        setLoadBearing([]);
      }

      if (graphRes.status === 'fulfilled' && graphRes.value.ok) {
        const d = await graphRes.value.json();
        setClaims(d.nodes ?? d.graph?.nodes ?? d.data?.nodes ?? []);
        anyOk = true;
      } else {
        setClaims([]);
      }

      if (posRes.status === 'fulfilled' && posRes.value.ok) {
        const d = await posRes.value.json();
        setPositions(d);
        anyOk = true;
      } else {
        setPositions(null);
      }

      if (!anyOk) {
        const firstFailed =
          cruxRes.status === 'fulfilled' ? `HTTP ${cruxRes.value.status}` : 'Network error';
        setError(`Failed to load reasoning data: ${firstFailed}`);
      }

      setLoadedId(debateId.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }, [backendUrl, debateId]);

  /* ---- Belief Network tab ---- */
  const renderBeliefNetwork = () => (
    <div className="space-y-6">
      {/* Crux Claims */}
      <div>
        <h2 className="text-xs font-theme-data text-[var(--accent)] mb-3">
          &gt; CRUX CLAIMS ({cruxes.length})
        </h2>
        {cruxes.length === 0 ? (
          <p className="text-text-muted font-theme-data text-sm">
            No crux claims found for this debate.
          </p>
        ) : (
          <div className="space-y-3">
            {cruxes.map((c, i) => (
              <div key={c.claim_id ?? i} className="p-4 border border-[var(--accent)]/20 bg-bg">
                <p className="text-sm font-theme-data text-text mb-3">{c.claim}</p>
                <div className="flex items-center gap-4 text-xs font-theme-data text-text-muted mb-2">
                  {c.source_agent && (
                    <span className="text-[var(--acid-cyan)]">{c.source_agent}</span>
                  )}
                  <span>Sensitivity: {(c.sensitivity * 100).toFixed(0)}%</span>
                </div>
                {/* Probability bar */}
                <div>
                  <div className="flex items-center justify-between text-xs text-text-muted font-theme-data mb-1">
                    <span>P = {c.probability.toFixed(2)}</span>
                    <span>{(c.probability * 100).toFixed(0)}%</span>
                  </div>
                  <div className="h-2 bg-bg border border-[var(--accent)]/20 rounded-sm overflow-hidden">
                    <div
                      className="h-full transition-all"
                      style={{
                        width: `${c.probability * 100}%`,
                        backgroundColor: 'var(--acid-green)',
                        opacity: 0.6,
                      }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Load-Bearing Claims */}
      <div>
        <h2 className="text-xs font-theme-data text-[var(--accent)] mb-3">
          &gt; LOAD-BEARING CLAIMS ({loadBearing.length})
        </h2>
        {loadBearing.length === 0 ? (
          <p className="text-text-muted font-theme-data text-sm">No load-bearing claims found.</p>
        ) : (
          <div className="space-y-3">
            {loadBearing.map((lb, i) => (
              <div key={lb.claim_id ?? i} className="p-4 border border-[var(--accent)]/20 bg-bg">
                <p className="text-sm font-theme-data text-text mb-2">{lb.claim}</p>
                <div className="flex items-center gap-4 text-xs font-theme-data text-text-muted mb-2">
                  {lb.source_agent && (
                    <span className="text-[var(--acid-cyan)]">{lb.source_agent}</span>
                  )}
                  <span>Centrality: {lb.centrality.toFixed(3)}</span>
                </div>
                {/* Centrality bar */}
                <div className="h-2 bg-bg border border-[var(--accent)]/20 rounded-sm overflow-hidden">
                  <div
                    className="h-full transition-all"
                    style={{
                      width: `${Math.min(lb.centrality * 100, 100)}%`,
                      backgroundColor: 'var(--acid-cyan, #00e5ff)',
                      opacity: 0.6,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  /* ---- Claims tab ---- */
  const renderClaims = () => (
    <div>
      <h2 className="text-xs font-theme-data text-[var(--accent)] mb-3">
        &gt; CLAIM GRAPH ({claims.length} claims)
      </h2>
      {claims.length === 0 ? (
        <p className="text-text-muted font-theme-data text-sm">No claims found for this debate.</p>
      ) : (
        <div className="space-y-3">
          {claims.map((c, i) => {
            const hasContradiction = c.contradicts && c.contradicts.length > 0;
            return (
              <div
                key={c.id || i}
                className={`p-3 border bg-bg ${
                  hasContradiction ? 'border-red-500/50' : 'border-[var(--accent)]/20'
                }`}
              >
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                  <span className="px-2 py-0.5 bg-[var(--accent)]/20 text-[var(--accent)] text-xs font-theme-data uppercase">
                    {c.type}
                  </span>
                  {c.agent && (
                    <span className="text-[var(--acid-cyan)] text-xs font-theme-data">
                      {c.agent}
                    </span>
                  )}
                  {c.evidence_count !== undefined && c.evidence_count > 0 && (
                    <span className="text-text-muted text-xs font-theme-data">
                      {c.evidence_count} evidence
                    </span>
                  )}
                  {hasContradiction && (
                    <span className="px-2 py-0.5 bg-red-500/20 text-red-400 text-xs font-theme-data">
                      CONTRADICTED
                    </span>
                  )}
                </div>
                <p className="text-sm font-theme-data text-text">{c.text}</p>
                {hasContradiction && (
                  <div className="mt-2 text-xs font-theme-data text-red-400/70">
                    Contradicts: {c.contradicts!.join(', ')}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );

  /* ---- Positions tab ---- */
  const renderPositions = () => {
    if (!positions) {
      return (
        <p className="text-text-muted font-theme-data text-sm">
          No position data found for this debate.
        </p>
      );
    }

    const agents = Object.keys(positions.positions);
    const maxRound = Math.max(
      ...agents.flatMap((a) => positions.positions[a].map((p) => p.round)),
      0,
    );
    const rounds = Array.from({ length: maxRound + 1 }, (_, i) => i);

    return (
      <div className="space-y-6">
        <h2 className="text-xs font-theme-data text-[var(--accent)] mb-3">
          &gt; POSITION EVOLUTION
        </h2>

        {/* Summary stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {(
            [
              ['Convergence', `${(positions.summary.convergence_score * 100).toFixed(0)}%`],
              ['Total Pivots', positions.summary.total_pivots],
              ['Reversals', positions.summary.reversals],
              ['Agents', agents.length],
            ] as [string, string | number][]
          ).map(([label, value]) => (
            <div key={label} className="p-3 border border-[var(--accent)]/20 bg-bg">
              <div className="text-xs font-theme-data text-text-muted">{label}</div>
              <div className="text-lg font-theme-data text-[var(--accent)]">{value}</div>
            </div>
          ))}
        </div>

        {/* Per-agent timelines */}
        <div className="space-y-4">
          {agents.map((agent) => {
            const records = positions.positions[agent];
            const agentPivots = positions.pivots.filter((p) => p.agent === agent);
            const pivotRounds = new Set(
              agentPivots.filter((p) => p.pivot_magnitude >= 0.3).map((p) => p.to_round),
            );
            const stability = positions.summary.stability_scores[agent] ?? 1;

            return (
              <div key={agent} className="p-4 border border-[var(--accent)]/20 bg-bg">
                <div className="flex items-center justify-between mb-3">
                  <span className="font-theme-data text-[var(--acid-cyan)] text-sm">{agent}</span>
                  <span className="text-xs font-theme-data text-text-muted">
                    stability: {(stability * 100).toFixed(0)}%
                  </span>
                </div>

                {/* Horizontal timeline */}
                <div className="flex gap-1">
                  {rounds.map((r) => {
                    const rec = records.find((p) => p.round === r);
                    const isPivot = pivotRounds.has(r);
                    const bg = rec ? stanceColor(rec.stance) : 'var(--border)';
                    const label = rec ? (STANCE_LABELS[rec.stance] ?? rec.stance) : '-';

                    return (
                      <div
                        key={r}
                        className="relative flex-1 group"
                        title={
                          rec
                            ? `R${r}: ${label} (${(rec.confidence * 100).toFixed(0)}%)`
                            : `R${r}: -`
                        }
                      >
                        <div
                          className="h-6 rounded-sm"
                          style={{ backgroundColor: bg, opacity: rec ? 1 : 0.3 }}
                        />
                        {isPivot && (
                          <div
                            className="absolute -top-1 left-1/2 -translate-x-1/2 w-2 h-2 rounded-full border border-bg"
                            style={{ backgroundColor: '#facc15' }}
                          />
                        )}
                        <div className="text-center text-[9px] text-text-muted font-theme-data mt-0.5">
                          R{r}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        {/* Pivot log */}
        {positions.pivots.length > 0 && (
          <div>
            <h3 className="text-xs font-theme-data text-[var(--accent)] mb-2">&gt; PIVOT LOG</h3>
            <div className="space-y-2">
              {positions.pivots.map((pivot, i) => (
                <div
                  key={i}
                  className={`p-2 border text-xs font-theme-data ${
                    pivot.pivot_type === 'reversal'
                      ? 'border-red-500/30 bg-red-500/5'
                      : 'border-[var(--accent)]/20 bg-bg'
                  }`}
                >
                  <span className="text-[var(--acid-cyan)]">{pivot.agent}</span>
                  <span className="text-text-muted mx-2">
                    R{pivot.from_round} {STANCE_LABELS[pivot.from_stance] ?? pivot.from_stance}
                    {' -> '}R{pivot.to_round} {STANCE_LABELS[pivot.to_stance] ?? pivot.to_stance}
                  </span>
                  <span
                    className={`px-1 py-0.5 text-[10px] uppercase ${
                      pivot.pivot_type === 'reversal'
                        ? 'bg-red-500/20 text-red-400'
                        : 'bg-[var(--accent)]/20 text-[var(--accent)]'
                    }`}
                  >
                    {pivot.pivot_type}
                  </span>
                  <span className="text-text-muted ml-2">
                    ({(pivot.pivot_magnitude * 100).toFixed(0)}% shift)
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Stance legend */}
        <div className="flex flex-wrap gap-3 text-xs font-theme-data text-text-muted">
          {Object.entries(STANCE_COLORS).map(([stance, color]) => (
            <div key={stance} className="flex items-center gap-1">
              <div className="w-3 h-3 rounded-sm" style={{ backgroundColor: color }} />
              <span>{stance.replace(/_/g, ' ')}</span>
            </div>
          ))}
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full" style={{ backgroundColor: '#facc15' }} />
            <span>pivot point</span>
          </div>
        </div>
      </div>
    );
  };

  /* ---- Tab config ---- */
  const tabs: { key: TabType; label: string }[] = [
    { key: 'belief', label: 'BELIEF NETWORK' },
    { key: 'claims', label: 'CLAIMS' },
    { key: 'positions', label: 'POSITIONS' },
  ];

  /* ---- Main render ---- */
  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10 font-theme-data">
        {/* Header */}
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs text-text-muted">
              <Link href="/" className="hover:text-[var(--accent)] transition-colors">
                DASHBOARD
              </Link>
              <span>/</span>
              <span className="text-[var(--accent)]">REASONING ENGINE</span>
            </div>
            <div className="flex items-center gap-3">
              <Link
                href="/argument-analysis"
                className="text-xs text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [ARGUMENTS]
              </Link>
              <Link
                href="/crux"
                className="text-xs text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [CRUX]
              </Link>
            </div>
          </div>
        </header>

        <div className="container mx-auto px-4 py-6">
          {/* Title */}
          <h1 className="text-2xl text-[var(--accent)] mb-4">{'>'} REASONING ENGINE</h1>

          {/* Search */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              loadData();
            }}
            className="mb-6 flex gap-2"
          >
            <input
              type="text"
              value={debateId}
              onChange={(e) => setDebateId(e.target.value)}
              placeholder="Enter debate ID..."
              className="flex-1 bg-surface border border-[var(--accent)]/30 px-4 py-2 text-sm text-text placeholder:text-text-muted/50 focus:outline-none focus:border-[var(--accent)]"
            />
            <button
              type="submit"
              disabled={loading || !debateId.trim()}
              className="px-6 py-2 border border-[var(--accent)] text-[var(--accent)] text-sm hover:bg-[var(--accent)]/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? 'LOADING...' : '[LOAD]'}
            </button>
          </form>

          {/* Error */}
          {error && (
            <div className="mb-6 p-4 border border-red-500/50 bg-red-500/10 text-red-400 text-sm">
              Error: {error}
            </div>
          )}

          {/* Empty state */}
          {!loadedId && !loading && !error && (
            <div className="flex items-center justify-center h-96 border border-[var(--accent)]/20 bg-surface/30">
              <div className="text-center text-text-muted">
                <p className="text-lg mb-2">&gt; REASONING ENGINE</p>
                <p className="text-sm">
                  Enter a debate ID to explore belief networks, claims, and position evolution
                </p>
              </div>
            </div>
          )}

          {/* Loading */}
          {loading && (
            <div className="flex items-center justify-center h-96 border border-[var(--accent)]/20 bg-surface/30">
              <div className="text-center text-[var(--accent)] animate-pulse">
                Loading reasoning data...
              </div>
            </div>
          )}

          {/* Tabbed content */}
          {loadedId && !loading && (
            <>
              {/* Tab bar */}
              <div className="flex border border-[var(--accent)]/20 border-b-0">
                {tabs.map((tab) => (
                  <button
                    key={tab.key}
                    onClick={() => setActiveTab(tab.key)}
                    className={`flex-1 px-4 py-2 text-xs transition-colors ${
                      activeTab === tab.key
                        ? 'bg-[var(--accent)]/20 text-[var(--accent)] border-b-2 border-[var(--accent)]'
                        : 'text-text-muted hover:text-[var(--accent)]'
                    }`}
                  >
                    [{tab.label}]
                  </button>
                ))}
              </div>

              <div className="border border-[var(--accent)]/20 bg-surface/30 min-h-[500px] p-4">
                {activeTab === 'belief' && renderBeliefNetwork()}
                {activeTab === 'claims' && renderClaims()}
                {activeTab === 'positions' && renderPositions()}
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <footer className="text-center text-xs py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // REASONING ENGINE</p>
        </footer>
      </main>
    </>
  );
}
