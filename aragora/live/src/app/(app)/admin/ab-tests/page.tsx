'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';

interface ABTest {
  id: string;
  agent: string;
  baseline_prompt_version: number;
  evolved_prompt_version: number;
  baseline_wins: number;
  evolved_wins: number;
  baseline_debates: number;
  evolved_debates: number;
  evolved_win_rate: number;
  baseline_win_rate: number;
  total_debates: number;
  sample_size: number;
  is_significant: boolean;
  started_at: string;
  concluded_at: string | null;
  status: 'active' | 'concluded' | 'cancelled';
  metadata?: Record<string, unknown>;
}

interface TestResult {
  test_id: string;
  winner: 'baseline' | 'evolved' | 'tie';
  confidence: number;
  recommendation: string;
  stats: {
    evolved_win_rate: number;
    baseline_win_rate: number;
    sample_size: number;
    total_debates: number;
    is_significant: boolean;
  };
}

export default function ABTestingDashboard() {
  const { config: backendConfig } = useBackend();
  const [tests, setTests] = useState<ABTest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [agentFilter, setAgentFilter] = useState<string>('');
  const [selectedTest, setSelectedTest] = useState<ABTest | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [concludeResult, setConcludeResult] = useState<TestResult | null>(null);

  // Create test form state
  const [newTestAgent, setNewTestAgent] = useState('');
  const [newTestBaseline, setNewTestBaseline] = useState(1);
  const [newTestEvolved, setNewTestEvolved] = useState(2);
  const [creating, setCreating] = useState(false);

  const fetchTests = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (statusFilter !== 'all') params.set('status', statusFilter);
      if (agentFilter) params.set('agent', agentFilter);
      params.set('limit', '100');

      const res = await fetch(`${backendConfig.api}/api/evolution/ab-tests?${params}`);
      if (!res.ok) throw new Error('Failed to fetch A/B tests');
      const data = await res.json();
      setTests(data.tests || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      // Demo data
      setTests([
        {
          id: 'demo-1',
          agent: 'claude',
          baseline_prompt_version: 1,
          evolved_prompt_version: 2,
          baseline_wins: 12,
          evolved_wins: 18,
          baseline_debates: 25,
          evolved_debates: 25,
          evolved_win_rate: 0.6,
          baseline_win_rate: 0.4,
          total_debates: 50,
          sample_size: 30,
          is_significant: true,
          started_at: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
          concluded_at: null,
          status: 'active',
        },
        {
          id: 'demo-2',
          agent: 'gpt4',
          baseline_prompt_version: 3,
          evolved_prompt_version: 4,
          baseline_wins: 8,
          evolved_wins: 7,
          baseline_debates: 15,
          evolved_debates: 15,
          evolved_win_rate: 0.47,
          baseline_win_rate: 0.53,
          total_debates: 30,
          sample_size: 15,
          is_significant: false,
          started_at: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(),
          concluded_at: null,
          status: 'active',
        },
        {
          id: 'demo-3',
          agent: 'gemini',
          baseline_prompt_version: 1,
          evolved_prompt_version: 2,
          baseline_wins: 5,
          evolved_wins: 25,
          baseline_debates: 30,
          evolved_debates: 30,
          evolved_win_rate: 0.83,
          baseline_win_rate: 0.17,
          total_debates: 60,
          sample_size: 30,
          is_significant: true,
          started_at: new Date(Date.now() - 14 * 24 * 60 * 60 * 1000).toISOString(),
          concluded_at: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(),
          status: 'concluded',
        },
      ]);
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, statusFilter, agentFilter]);

  useEffect(() => {
    fetchTests();
  }, [fetchTests]);

  const createTest = async () => {
    if (!newTestAgent) return;
    setCreating(true);
    try {
      const res = await fetch(`${backendConfig.api}/api/evolution/ab-tests`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent: newTestAgent,
          baseline_version: newTestBaseline,
          evolved_version: newTestEvolved,
        }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || 'Failed to create test');
      }
      setShowCreateModal(false);
      setNewTestAgent('');
      fetchTests();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create test');
    } finally {
      setCreating(false);
    }
  };

  const concludeTest = async (testId: string, force: boolean = false) => {
    try {
      const res = await fetch(`${backendConfig.api}/api/evolution/ab-tests/${testId}/conclude`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force }),
      });
      if (!res.ok) throw new Error('Failed to conclude test');
      const data = await res.json();
      setConcludeResult(data.result);
      fetchTests();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to conclude test');
    }
  };

  const cancelTest = async (testId: string) => {
    if (!confirm('Are you sure you want to cancel this test?')) return;
    try {
      const res = await fetch(`${backendConfig.api}/api/evolution/ab-tests/${testId}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error('Failed to cancel test');
      setSelectedTest(null);
      fetchTests();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel test');
    }
  };

  const getWinRateColor = (rate: number) => {
    if (rate >= 0.6) return 'text-success';
    if (rate >= 0.5) return 'text-[var(--acid-yellow)]';
    return 'text-[var(--crimson)]';
  };

  const uniqueAgents = Array.from(new Set(tests.map((t) => t.agent)));

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
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)]"
              >
                [ADMIN]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <div className="container mx-auto px-4 py-6">
          <PanelErrorBoundary panelName="ABTesting">
            {/* Page Header */}
            <div className="flex items-center justify-between mb-6">
              <div>
                <div className="text-xs font-theme-data text-text-muted mb-1">
                  <Link href="/admin" className="hover:text-[var(--accent)]">
                    Admin
                  </Link>
                  <span className="mx-2">/</span>
                  <span className="text-[var(--accent)]">A/B Tests</span>
                </div>
                <h1 className="text-2xl font-theme-data text-[var(--accent)]">
                  A/B Testing Dashboard
                </h1>
                <p className="text-text-muted font-theme-data text-sm mt-1">
                  Compare baseline vs evolved agent prompts through controlled experiments
                </p>
              </div>
              <button
                onClick={() => setShowCreateModal(true)}
                className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors"
              >
                + New Test
              </button>
            </div>

            {/* Filters */}
            <div className="card p-4 mb-6">
              <div className="flex flex-wrap gap-4 items-center">
                <div>
                  <label className="text-xs font-theme-data text-text-muted block mb-1">
                    Status
                  </label>
                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    className="bg-surface border border-border rounded px-3 py-1.5 text-sm font-theme-data"
                  >
                    <option value="all">All</option>
                    <option value="active">Active</option>
                    <option value="concluded">Concluded</option>
                    <option value="cancelled">Cancelled</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-theme-data text-text-muted block mb-1">
                    Agent
                  </label>
                  <select
                    value={agentFilter}
                    onChange={(e) => setAgentFilter(e.target.value)}
                    className="bg-surface border border-border rounded px-3 py-1.5 text-sm font-theme-data"
                  >
                    <option value="">All Agents</option>
                    {uniqueAgents.map((a) => (
                      <option key={a} value={a}>
                        {a}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex-1" />
                <div className="text-xs font-theme-data text-text-muted">
                  {tests.length} tests found
                </div>
              </div>
            </div>

            {error && (
              <div className="mb-4 p-3 bg-[var(--crimson)]/20 border border-[var(--crimson)]/30 rounded text-[var(--crimson)] font-theme-data text-sm">
                {error}
                <span className="ml-2 text-text-muted">(showing demo data)</span>
              </div>
            )}

            {loading ? (
              <div className="card p-8 text-center">
                <div className="animate-pulse font-theme-data text-text-muted">
                  Loading A/B tests...
                </div>
              </div>
            ) : (
              <div className="grid gap-4">
                {tests.map((test) => (
                  <div
                    key={test.id}
                    className={`card p-4 cursor-pointer transition-colors ${
                      selectedTest?.id === test.id
                        ? 'border-[var(--accent)]'
                        : 'hover:border-[var(--accent)]/50'
                    }`}
                    onClick={() => setSelectedTest(selectedTest?.id === test.id ? null : test)}
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="flex items-center gap-3 mb-2">
                          <span className="font-theme-data font-bold text-lg">{test.agent}</span>
                          <span
                            className={`text-xs font-theme-data px-2 py-0.5 rounded ${
                              test.status === 'active'
                                ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                                : test.status === 'concluded'
                                  ? 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)]'
                                  : 'bg-[var(--crimson)]/20 text-[var(--crimson)]'
                            }`}
                          >
                            {test.status.toUpperCase()}
                          </span>
                          {test.is_significant && (
                            <span className="text-xs font-theme-data px-2 py-0.5 bg-purple-500/20 text-purple-400 rounded">
                              SIGNIFICANT
                            </span>
                          )}
                        </div>
                        <div className="text-xs font-theme-data text-text-muted">
                          v{test.baseline_prompt_version} (baseline) vs v
                          {test.evolved_prompt_version} (evolved)
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-xs font-theme-data text-text-muted mb-1">
                          {test.total_debates} debates
                        </div>
                        <div className="text-xs font-theme-data text-text-muted">
                          Started {new Date(test.started_at).toLocaleDateString()}
                        </div>
                      </div>
                    </div>

                    {/* Win Rate Comparison */}
                    <div className="mt-4 grid grid-cols-2 gap-4">
                      <div className="bg-surface p-3 rounded">
                        <div className="text-xs font-theme-data text-text-muted mb-1">
                          BASELINE (v{test.baseline_prompt_version})
                        </div>
                        <div
                          className={`text-2xl font-theme-data ${getWinRateColor(test.baseline_win_rate)}`}
                        >
                          {(test.baseline_win_rate * 100).toFixed(1)}%
                        </div>
                        <div className="text-xs font-theme-data text-text-muted">
                          {test.baseline_wins} wins / {test.baseline_debates} debates
                        </div>
                      </div>
                      <div className="bg-surface p-3 rounded">
                        <div className="text-xs font-theme-data text-text-muted mb-1">
                          EVOLVED (v{test.evolved_prompt_version})
                        </div>
                        <div
                          className={`text-2xl font-theme-data ${getWinRateColor(test.evolved_win_rate)}`}
                        >
                          {(test.evolved_win_rate * 100).toFixed(1)}%
                        </div>
                        <div className="text-xs font-theme-data text-text-muted">
                          {test.evolved_wins} wins / {test.evolved_debates} debates
                        </div>
                      </div>
                    </div>

                    {/* Win Rate Bar */}
                    <div className="mt-4">
                      <div className="h-2 bg-surface rounded overflow-hidden flex">
                        <div
                          className="h-full bg-[var(--crimson)]/70"
                          style={{ width: `${test.baseline_win_rate * 100}%` }}
                        />
                        <div
                          className="h-full bg-[var(--accent)]/70"
                          style={{ width: `${test.evolved_win_rate * 100}%` }}
                        />
                      </div>
                      <div className="flex justify-between text-xs font-theme-data text-text-muted mt-1">
                        <span>Baseline</span>
                        <span>Sample: {test.sample_size} decisive</span>
                        <span>Evolved</span>
                      </div>
                    </div>

                    {/* Actions */}
                    {selectedTest?.id === test.id && test.status === 'active' && (
                      <div className="mt-4 pt-4 border-t border-border flex gap-3">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            concludeTest(test.id);
                          }}
                          className="px-3 py-1.5 bg-[var(--acid-cyan)]/20 border border-[var(--acid-cyan)] text-[var(--acid-cyan)] font-theme-data text-xs rounded hover:bg-[var(--acid-cyan)]/30"
                        >
                          Conclude Test
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            concludeTest(test.id, true);
                          }}
                          className="px-3 py-1.5 bg-acid-yellow/20 border border-acid-yellow text-[var(--acid-yellow)] font-theme-data text-xs rounded hover:bg-acid-yellow/30"
                        >
                          Force Conclude
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            cancelTest(test.id);
                          }}
                          className="px-3 py-1.5 bg-[var(--crimson)]/20 border border-[var(--crimson)] text-[var(--crimson)] font-theme-data text-xs rounded hover:bg-[var(--crimson)]/30"
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                  </div>
                ))}

                {tests.length === 0 && (
                  <div className="card p-8 text-center">
                    <div className="font-theme-data text-text-muted">No A/B tests found</div>
                    <button
                      onClick={() => setShowCreateModal(true)}
                      className="mt-4 px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-sm rounded"
                    >
                      Create First Test
                    </button>
                  </div>
                )}
              </div>
            )}
          </PanelErrorBoundary>
        </div>

        {/* Create Modal */}
        {showCreateModal && (
          <div
            className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
            onClick={() => setShowCreateModal(false)}
          >
            <div className="card p-6 max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
              <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">Create A/B Test</h2>
              <div className="space-y-4">
                <div>
                  <label className="text-xs font-theme-data text-text-muted block mb-1">
                    Agent
                  </label>
                  <input
                    type="text"
                    value={newTestAgent}
                    onChange={(e) => setNewTestAgent(e.target.value)}
                    placeholder="e.g., claude"
                    className="w-full bg-surface border border-border rounded px-3 py-2 font-theme-data text-sm"
                  />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs font-theme-data text-text-muted block mb-1">
                      Baseline Version
                    </label>
                    <input
                      type="number"
                      value={newTestBaseline}
                      onChange={(e) => setNewTestBaseline(parseInt(e.target.value))}
                      min={1}
                      className="w-full bg-surface border border-border rounded px-3 py-2 font-theme-data text-sm"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-theme-data text-text-muted block mb-1">
                      Evolved Version
                    </label>
                    <input
                      type="number"
                      value={newTestEvolved}
                      onChange={(e) => setNewTestEvolved(parseInt(e.target.value))}
                      min={1}
                      className="w-full bg-surface border border-border rounded px-3 py-2 font-theme-data text-sm"
                    />
                  </div>
                </div>
                <div className="flex gap-3 pt-2">
                  <button
                    onClick={() => setShowCreateModal(false)}
                    className="flex-1 px-4 py-2 border border-border font-theme-data text-sm rounded hover:border-text-muted"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={createTest}
                    disabled={!newTestAgent || creating}
                    className="flex-1 px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 disabled:opacity-50"
                  >
                    {creating ? 'Creating...' : 'Create Test'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Conclude Result Modal */}
        {concludeResult && (
          <div
            className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
            onClick={() => setConcludeResult(null)}
          >
            <div className="card p-6 max-w-lg w-full mx-4" onClick={(e) => e.stopPropagation()}>
              <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">Test Concluded</h2>
              <div className="space-y-4">
                <div className="text-center">
                  <div className="text-xs font-theme-data text-text-muted mb-2">WINNER</div>
                  <div
                    className={`text-3xl font-theme-data font-bold ${
                      concludeResult.winner === 'evolved'
                        ? 'text-success'
                        : concludeResult.winner === 'baseline'
                          ? 'text-[var(--crimson)]'
                          : 'text-[var(--acid-yellow)]'
                    }`}
                  >
                    {concludeResult.winner.toUpperCase()}
                  </div>
                  <div className="text-sm font-theme-data text-text-muted mt-2">
                    Confidence: {(concludeResult.confidence * 100).toFixed(1)}%
                  </div>
                </div>
                <div className="bg-surface p-4 rounded">
                  <div className="text-xs font-theme-data text-text-muted mb-2">RECOMMENDATION</div>
                  <p className="font-theme-data text-sm">{concludeResult.recommendation}</p>
                </div>
                <div className="grid grid-cols-2 gap-4 text-center">
                  <div className="bg-surface p-3 rounded">
                    <div className="text-2xl font-theme-data">
                      {(concludeResult.stats.baseline_win_rate * 100).toFixed(1)}%
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">Baseline Win Rate</div>
                  </div>
                  <div className="bg-surface p-3 rounded">
                    <div className="text-2xl font-theme-data">
                      {(concludeResult.stats.evolved_win_rate * 100).toFixed(1)}%
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">Evolved Win Rate</div>
                  </div>
                </div>
                <button
                  onClick={() => setConcludeResult(null)}
                  className="w-full px-4 py-2 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/10"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // A/B TESTING</p>
        </footer>
      </main>
    </>
  );
}
