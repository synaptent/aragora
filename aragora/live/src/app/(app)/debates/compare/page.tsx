'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { getAgentColors } from '@/utils/agentColors';
import { logger } from '@/utils/logger';
import { normalizeDecisionPackage, type DecisionPackage } from '../[id]/normalizeDecisionPackage';

function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function formatCurrency(value: number): string {
  return `$${value.toFixed(4)}`;
}

function formatDuration(value: number): string {
  return value > 0 ? `${Math.round(value)}s` : '--';
}

function formatSignedDelta(value: number, digits = 0): string {
  const fixed = digits > 0 ? value.toFixed(digits) : Math.round(value).toString();
  return value > 0 ? `+${fixed}` : fixed;
}

function trimId(value: string): string {
  return value.trim();
}

function didOutcomeShift(left: DecisionPackage, right: DecisionPackage): boolean {
  return (
    left.verdict !== right.verdict ||
    left.consensus_reached !== right.consensus_reached ||
    left.final_answer.trim() !== right.final_answer.trim()
  );
}

function getAgentDiff(left: string[], right: string[]) {
  const rightSet = new Set(right);
  const leftSet = new Set(left);

  return {
    shared: left.filter((agent) => rightSet.has(agent)),
    leftOnly: left.filter((agent) => !rightSet.has(agent)),
    rightOnly: right.filter((agent) => !leftSet.has(agent)),
  };
}

async function fetchDecisionPackage(apiBase: string, debateId: string): Promise<DecisionPackage> {
  const response = await fetch(`${apiBase}/api/v1/debates/${debateId}/package`, {
    signal: AbortSignal.timeout(10000),
  });

  if (!response.ok) {
    throw new Error(`Failed to load ${debateId} (HTTP ${response.status})`);
  }

  const data = await response.json();
  return normalizeDecisionPackage(data, debateId);
}

interface MetricRow {
  label: string;
  left: string;
  right: string;
  delta: string;
}

function buildMetricRows(left: DecisionPackage, right: DecisionPackage): MetricRow[] {
  const confidenceDelta = (left.confidence - right.confidence) * 100;
  const durationDelta = left.duration_seconds - right.duration_seconds;
  const costDelta = left.total_cost - right.total_cost;

  return [
    {
      label: 'Verdict',
      left: left.verdict || 'UNKNOWN',
      right: right.verdict || 'UNKNOWN',
      delta: left.verdict === right.verdict ? 'Aligned' : 'Changed',
    },
    {
      label: 'Consensus',
      left: left.consensus_reached ? 'Yes' : 'No',
      right: right.consensus_reached ? 'Yes' : 'No',
      delta: left.consensus_reached === right.consensus_reached ? 'Aligned' : 'Different',
    },
    {
      label: 'Confidence',
      left: formatConfidence(left.confidence),
      right: formatConfidence(right.confidence),
      delta: `${formatSignedDelta(confidenceDelta)} pts`,
    },
    {
      label: 'Agents',
      left: `${left.agents.length}`,
      right: `${right.agents.length}`,
      delta: formatSignedDelta(left.agents.length - right.agents.length),
    },
    {
      label: 'Rounds',
      left: `${left.rounds}`,
      right: `${right.rounds}`,
      delta: formatSignedDelta(left.rounds - right.rounds),
    },
    {
      label: 'Duration',
      left: formatDuration(left.duration_seconds),
      right: formatDuration(right.duration_seconds),
      delta: `${formatSignedDelta(durationDelta)}s`,
    },
    {
      label: 'Total Cost',
      left: formatCurrency(left.total_cost),
      right: formatCurrency(right.total_cost),
      delta: formatCurrency(costDelta),
    },
  ];
}

interface DebatePackageCardProps {
  accent: string;
  accentBorder: string;
  debateId: string;
  label: string;
  pkg: DecisionPackage;
}

function DebatePackageCard({ accent, accentBorder, debateId, label, pkg }: DebatePackageCardProps) {
  return (
    <section className={`border ${accentBorder} bg-[var(--surface)] p-5`}>
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <div className={`text-xs font-theme-data ${accent} mb-1`}>{label}</div>
          <Link
            href={`/debates/${debateId}`}
            className="text-sm font-theme-data text-[var(--acid-green)] hover:text-[var(--acid-cyan)] transition-colors"
          >
            {debateId}
          </Link>
        </div>
        <div className="text-xs font-theme-data text-[var(--text-muted)]">
          {new Date(pkg.created_at).toLocaleString()}
        </div>
      </div>

      <h2 className="text-lg font-theme-data text-[var(--text)] mb-3">{pkg.question}</h2>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <span className={`px-2 py-1 text-xs font-theme-data border ${accentBorder} ${accent}`}>
          {pkg.verdict || 'UNKNOWN'}
        </span>
        <span
          className={`px-2 py-1 text-xs font-theme-data border ${
            pkg.consensus_reached
              ? 'border-[var(--acid-green)]/40 text-[var(--acid-green)]'
              : 'border-[var(--warning)]/40 text-[var(--warning)]'
          }`}
        >
          {pkg.consensus_reached ? 'CONSENSUS' : 'NO CONSENSUS'}
        </span>
        <span className="px-2 py-1 text-xs font-theme-data border border-[var(--border)] text-[var(--text-muted)]">
          {formatConfidence(pkg.confidence)} confidence
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 mb-5 text-xs font-theme-data">
        <div className="border border-[var(--border)] bg-[var(--bg)] p-3">
          <div className="text-[var(--text-muted)] mb-1">Agents</div>
          <div className="text-[var(--text)]">{pkg.agents.length}</div>
        </div>
        <div className="border border-[var(--border)] bg-[var(--bg)] p-3">
          <div className="text-[var(--text-muted)] mb-1">Rounds</div>
          <div className="text-[var(--text)]">{pkg.rounds}</div>
        </div>
        <div className="border border-[var(--border)] bg-[var(--bg)] p-3">
          <div className="text-[var(--text-muted)] mb-1">Duration</div>
          <div className="text-[var(--text)]">{formatDuration(pkg.duration_seconds)}</div>
        </div>
        <div className="border border-[var(--border)] bg-[var(--bg)] p-3">
          <div className="text-[var(--text-muted)] mb-1">Total Cost</div>
          <div className="text-[var(--text)]">{formatCurrency(pkg.total_cost)}</div>
        </div>
      </div>

      <div className="mb-5">
        <div className="text-xs font-theme-data text-[var(--text-muted)] mb-2">
          AGENT CONFIGURATION
        </div>
        <div className="flex flex-wrap gap-2">
          {pkg.agents.length > 0 ? (
            pkg.agents.map((agent) => {
              const colors = getAgentColors(agent);
              return (
                <span
                  key={agent}
                  className={`px-2 py-1 text-xs font-theme-data ${colors.bg} ${colors.text}`}
                >
                  {agent}
                </span>
              );
            })
          ) : (
            <span className="text-xs font-theme-data text-[var(--text-muted)]">
              No agent roster recorded.
            </span>
          )}
        </div>
      </div>

      <div className="mb-5">
        <div className="text-xs font-theme-data text-[var(--text-muted)] mb-2">FINAL ANSWER</div>
        <div className="border border-[var(--border)] bg-[var(--bg)] p-4 text-sm whitespace-pre-wrap">
          {pkg.final_answer || 'No final answer recorded.'}
        </div>
      </div>

      {pkg.explanation && (
        <div className="mb-5">
          <div className="text-xs font-theme-data text-[var(--text-muted)] mb-2">
            RATIONALE SNAPSHOT
          </div>
          <div className="border border-[var(--border)] bg-[var(--bg)] p-4 text-sm whitespace-pre-wrap">
            {pkg.explanation}
          </div>
        </div>
      )}

      <div>
        <div className="text-xs font-theme-data text-[var(--text-muted)] mb-2">NEXT STEPS</div>
        {pkg.next_steps.length > 0 ? (
          <div className="space-y-2">
            {pkg.next_steps.map((step, index) => (
              <div
                key={`${step.action}-${index}`}
                className="border border-[var(--border)] bg-[var(--bg)] p-3"
              >
                <div className="text-[10px] font-theme-data text-[var(--acid-cyan)] mb-1">
                  {step.priority.toUpperCase()}
                </div>
                <div className="text-sm">{step.action}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-xs font-theme-data text-[var(--text-muted)]">
            No next steps recorded.
          </div>
        )}
      </div>
    </section>
  );
}

export default function DebateComparePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { config: backendConfig } = useBackend();

  const selectedLeftId = trimId(searchParams.get('left') ?? '');
  const selectedRightId = trimId(searchParams.get('right') ?? '');

  const [leftInput, setLeftInput] = useState(selectedLeftId);
  const [rightInput, setRightInput] = useState(selectedRightId);
  const [leftPkg, setLeftPkg] = useState<DecisionPackage | null>(null);
  const [rightPkg, setRightPkg] = useState<DecisionPackage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLeftInput(selectedLeftId);
    setRightInput(selectedRightId);
  }, [selectedLeftId, selectedRightId]);

  useEffect(() => {
    let cancelled = false;

    async function loadPackages() {
      if (!selectedLeftId || !selectedRightId) {
        setLeftPkg(null);
        setRightPkg(null);
        setLoading(false);
        setError(null);
        return;
      }

      if (selectedLeftId === selectedRightId) {
        setLeftPkg(null);
        setRightPkg(null);
        setLoading(false);
        setError('Select two different debate IDs to compare.');
        return;
      }

      setLoading(true);
      setError(null);

      try {
        const [left, right] = await Promise.all([
          fetchDecisionPackage(backendConfig.api, selectedLeftId),
          fetchDecisionPackage(backendConfig.api, selectedRightId),
        ]);

        if (cancelled) return;
        setLeftPkg(left);
        setRightPkg(right);
      } catch (loadError) {
        logger.error('Failed to load debate comparison:', loadError);
        if (cancelled) return;
        setLeftPkg(null);
        setRightPkg(null);
        setError('Unable to load one or both debate results. Check the IDs and try again.');
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadPackages();

    return () => {
      cancelled = true;
    };
  }, [backendConfig.api, selectedLeftId, selectedRightId]);

  const submitComparison = () => {
    const left = trimId(leftInput);
    const right = trimId(rightInput);
    const params = new URLSearchParams();

    if (left) params.set('left', left);
    if (right) params.set('right', right);

    const query = params.toString();
    router.replace(query ? `/debates/compare?${query}` : '/debates/compare');
  };

  const swapSides = () => {
    setLeftInput(rightInput);
    setRightInput(leftInput);
  };

  const readyToCompare =
    trimId(leftInput).length > 0 &&
    trimId(rightInput).length > 0 &&
    trimId(leftInput) !== trimId(rightInput);

  const agentDiff = leftPkg && rightPkg ? getAgentDiff(leftPkg.agents, rightPkg.agents) : null;
  const comparisonRows = leftPkg && rightPkg ? buildMetricRows(leftPkg, rightPkg) : [];
  const outcomeShift = leftPkg && rightPkg ? didOutcomeShift(leftPkg, rightPkg) : false;

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="container mx-auto px-4 py-6">
          <div className="mb-4 text-xs font-theme-data text-[var(--text-muted)]">
            <Link href="/debates" className="hover:text-[var(--acid-green)] transition-colors">
              Debates
            </Link>
            <span className="mx-2">/</span>
            <span className="text-[var(--acid-cyan)]">Compare</span>
          </div>

          <div className="border border-[var(--acid-cyan)]/30 bg-[var(--surface)] p-6 mb-6">
            <div className="flex flex-wrap items-start justify-between gap-4 mb-4">
              <div>
                <h1 className="text-xl font-theme-data text-[var(--acid-cyan)] mb-2">
                  {'>'} DEBATE RESULT COMPARISON
                </h1>
                <p className="text-sm font-theme-data text-[var(--text-muted)] max-w-3xl">
                  Load two completed debate runs side by side to see how agent rosters, confidence,
                  and final outcomes changed.
                </p>
              </div>
              <Link
                href="/debates"
                className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-cyan)]/40 transition-colors"
              >
                BACK TO ARCHIVE
              </Link>
            </div>

            <form
              className="grid gap-4 lg:grid-cols-[1fr_1fr_auto_auto]"
              onSubmit={(event) => {
                event.preventDefault();
                submitComparison();
              }}
            >
              <label className="block">
                <span className="block text-xs font-theme-data text-[var(--text-muted)] mb-2">
                  LEFT DEBATE ID
                </span>
                <input
                  value={leftInput}
                  onChange={(event) => setLeftInput(event.target.value)}
                  placeholder="debate-123"
                  className="w-full bg-[var(--bg)] border border-[var(--border)] px-3 py-2 text-sm font-theme-data text-[var(--text)] focus:outline-none focus:border-[var(--acid-cyan)]/50"
                />
              </label>

              <label className="block">
                <span className="block text-xs font-theme-data text-[var(--text-muted)] mb-2">
                  RIGHT DEBATE ID
                </span>
                <input
                  value={rightInput}
                  onChange={(event) => setRightInput(event.target.value)}
                  placeholder="debate-456"
                  className="w-full bg-[var(--bg)] border border-[var(--border)] px-3 py-2 text-sm font-theme-data text-[var(--text)] focus:outline-none focus:border-[var(--acid-cyan)]/50"
                />
              </label>

              <button
                type="button"
                onClick={swapSides}
                className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-cyan)]/40 transition-colors self-end"
              >
                SWAP
              </button>

              <button
                type="submit"
                disabled={!readyToCompare}
                className="px-4 py-2 text-xs font-theme-data bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30 hover:bg-[var(--acid-cyan)]/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed self-end"
              >
                LOAD COMPARISON
              </button>
            </form>

            {!readyToCompare &&
              leftInput &&
              rightInput &&
              trimId(leftInput) === trimId(rightInput) && (
                <div className="mt-3 text-xs font-theme-data text-[var(--warning)]">
                  Select two different debate IDs to compare.
                </div>
              )}
          </div>

          {loading && (
            <div className="border border-[var(--acid-green)]/30 bg-[var(--surface)] p-8 text-center text-sm font-theme-data text-[var(--acid-green)] animate-pulse">
              {'>'} LOADING DEBATE PACKAGES...
            </div>
          )}

          {!loading && error && (
            <div className="border border-[var(--warning)]/30 bg-[var(--warning)]/10 p-4 text-sm font-theme-data text-[var(--warning)]">
              {error}
            </div>
          )}

          {!loading && !error && (!leftPkg || !rightPkg) && (
            <div className="border border-[var(--border)] bg-[var(--surface)] p-8 text-center">
              <div className="text-sm font-theme-data text-[var(--text)] mb-2">
                Pick two debates to unlock the side-by-side view.
              </div>
              <div className="text-xs font-theme-data text-[var(--text-muted)]">
                Start from the archive&apos;s compare queue or paste two debate IDs above.
              </div>
            </div>
          )}

          {!loading && !error && leftPkg && rightPkg && agentDiff && (
            <div className="space-y-6">
              <div
                className={`border p-4 ${
                  outcomeShift
                    ? 'border-[var(--acid-cyan)]/40 bg-[var(--acid-cyan)]/5'
                    : 'border-[var(--acid-green)]/40 bg-[var(--acid-green)]/5'
                }`}
              >
                <div
                  className={`text-xs font-theme-data mb-2 ${
                    outcomeShift ? 'text-[var(--acid-cyan)]' : 'text-[var(--acid-green)]'
                  }`}
                >
                  {outcomeShift ? 'OUTCOME SHIFT DETECTED' : 'OUTCOME STAYED ALIGNED'}
                </div>
                <p className="text-sm text-[var(--text)]">
                  {outcomeShift
                    ? 'The two debate configurations landed on different outcomes, consensus states, or final answers.'
                    : 'The two debate configurations converged on the same outcome even though the setup changed.'}
                </p>
              </div>

              <div className="border border-[var(--border)] bg-[var(--surface)] p-5 overflow-x-auto">
                <div className="text-xs font-theme-data text-[var(--text-muted)] mb-4">
                  CONFIGURATION DELTA
                </div>
                <div className="min-w-[640px]">
                  <div className="grid grid-cols-[minmax(120px,1.2fr)_1fr_1fr_1fr] gap-3 text-xs font-theme-data text-[var(--text-muted)] mb-2">
                    <div>Metric</div>
                    <div>Left</div>
                    <div>Right</div>
                    <div>Delta</div>
                  </div>
                  {comparisonRows.map((row) => (
                    <div
                      key={row.label}
                      className="grid grid-cols-[minmax(120px,1.2fr)_1fr_1fr_1fr] gap-3 py-3 border-t border-[var(--border)] text-sm"
                    >
                      <div className="font-theme-data text-[var(--text-muted)]">{row.label}</div>
                      <div>{row.left}</div>
                      <div>{row.right}</div>
                      <div className="text-[var(--acid-cyan)] font-theme-data">{row.delta}</div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="grid gap-4 lg:grid-cols-3">
                <div className="border border-[var(--border)] bg-[var(--surface)] p-4">
                  <div className="text-xs font-theme-data text-[var(--text-muted)] mb-2">
                    SHARED AGENTS
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {agentDiff.shared.length > 0 ? (
                      agentDiff.shared.map((agent) => (
                        <span
                          key={agent}
                          className="px-2 py-1 text-xs font-theme-data border border-[var(--border)] bg-[var(--bg)]"
                        >
                          {agent}
                        </span>
                      ))
                    ) : (
                      <span className="text-xs font-theme-data text-[var(--text-muted)]">
                        No overlap
                      </span>
                    )}
                  </div>
                </div>
                <div className="border border-[var(--border)] bg-[var(--surface)] p-4">
                  <div className="text-xs font-theme-data text-[var(--text-muted)] mb-2">
                    LEFT ONLY
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {agentDiff.leftOnly.length > 0 ? (
                      agentDiff.leftOnly.map((agent) => (
                        <span
                          key={agent}
                          className="px-2 py-1 text-xs font-theme-data border border-[var(--acid-green)]/30 bg-[var(--acid-green)]/10 text-[var(--acid-green)]"
                        >
                          {agent}
                        </span>
                      ))
                    ) : (
                      <span className="text-xs font-theme-data text-[var(--text-muted)]">None</span>
                    )}
                  </div>
                </div>
                <div className="border border-[var(--border)] bg-[var(--surface)] p-4">
                  <div className="text-xs font-theme-data text-[var(--text-muted)] mb-2">
                    RIGHT ONLY
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {agentDiff.rightOnly.length > 0 ? (
                      agentDiff.rightOnly.map((agent) => (
                        <span
                          key={agent}
                          className="px-2 py-1 text-xs font-theme-data border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)]"
                        >
                          {agent}
                        </span>
                      ))
                    ) : (
                      <span className="text-xs font-theme-data text-[var(--text-muted)]">None</span>
                    )}
                  </div>
                </div>
              </div>

              <div className="grid gap-6 xl:grid-cols-2">
                <DebatePackageCard
                  accent="text-[var(--acid-green)]"
                  accentBorder="border-[var(--acid-green)]/30"
                  debateId={selectedLeftId}
                  label="LEFT RUN"
                  pkg={leftPkg}
                />
                <DebatePackageCard
                  accent="text-[var(--acid-cyan)]"
                  accentBorder="border-[var(--acid-cyan)]/30"
                  debateId={selectedRightId}
                  label="RIGHT RUN"
                  pkg={rightPkg}
                />
              </div>
            </div>
          )}
        </div>
      </main>
    </>
  );
}
