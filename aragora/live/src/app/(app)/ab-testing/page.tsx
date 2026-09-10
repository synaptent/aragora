'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { useAuth } from '@/context/AuthContext';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { API_BASE_URL } from '@/config';

const API_BASE = API_BASE_URL;

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
  metadata: Record<string, unknown>;
}

type ViewMode = 'list' | 'create' | 'detail';

export default function ABTestingPage() {
  const { tokens } = useAuth();
  const [tests, setTests] = useState<ABTest[]>([]);
  const [selectedTest, setSelectedTest] = useState<ABTest | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [agentFilter, setAgentFilter] = useState<string>('');

  // Create form state
  const [createForm, setCreateForm] = useState({
    agent: '',
    baseline_version: '',
    evolved_version: '',
    description: '',
  });
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const fetchTests = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (statusFilter) params.append('status', statusFilter);
      if (agentFilter) params.append('agent', agentFilter);
      params.append('limit', '100');

      const response = await fetch(`${API_BASE}/api/evolution/ab-tests?${params}`, {
        headers: { Authorization: `Bearer ${tokens?.access_token}` },
      });

      if (!response.ok) {
        throw new Error('Failed to fetch A/B tests');
      }

      const data = await response.json();
      setTests(data.tests || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tests');
    } finally {
      setLoading(false);
    }
  }, [tokens, statusFilter, agentFilter]);

  useEffect(() => {
    if (tokens?.access_token) {
      fetchTests();
    }
  }, [fetchTests, tokens]);

  const handleCreateTest = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateLoading(true);
    setCreateError(null);

    try {
      const response = await fetch(`${API_BASE}/api/evolution/ab-tests`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token}`,
        },
        body: JSON.stringify({
          agent: createForm.agent,
          baseline_version: parseInt(createForm.baseline_version),
          evolved_version: parseInt(createForm.evolved_version),
          metadata: createForm.description ? { description: createForm.description } : undefined,
        }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to create test');
      }

      const data = await response.json();
      setTests([data.test, ...tests]);
      setViewMode('list');
      setCreateForm({ agent: '', baseline_version: '', evolved_version: '', description: '' });
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'Failed to create test');
    } finally {
      setCreateLoading(false);
    }
  };

  const handleConcludeTest = async (testId: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/evolution/ab-tests/${testId}/conclude`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token}`,
        },
        body: JSON.stringify({ force: false }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to conclude test');
      }

      await fetchTests();
      if (selectedTest?.id === testId) {
        const refreshed = tests.find((t) => t.id === testId);
        if (refreshed) setSelectedTest(refreshed);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to conclude test');
    }
  };

  const handleCancelTest = async (testId: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/evolution/ab-tests/${testId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${tokens?.access_token}` },
      });

      if (!response.ok) {
        throw new Error('Failed to cancel test');
      }

      await fetchTests();
      if (selectedTest?.id === testId) {
        setSelectedTest(null);
        setViewMode('list');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel test');
    }
  };

  const viewTestDetail = (test: ABTest) => {
    setSelectedTest(test);
    setViewMode('detail');
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'active':
        return (
          <span className="px-2 py-0.5 bg-[var(--accent)]/20 text-[var(--accent)] text-xs">
            ACTIVE
          </span>
        );
      case 'concluded':
        return (
          <span className="px-2 py-0.5 bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] text-xs">
            CONCLUDED
          </span>
        );
      case 'cancelled':
        return <span className="px-2 py-0.5 bg-warning/20 text-warning text-xs">CANCELLED</span>;
      default:
        return (
          <span className="px-2 py-0.5 bg-text-muted/20 text-text-muted text-xs">
            {status.toUpperCase()}
          </span>
        );
    }
  };

  const getWinRateColor = (rate: number) => {
    if (rate >= 0.6) return 'text-[var(--accent)]';
    if (rate >= 0.5) return 'text-[var(--acid-cyan)]';
    if (rate >= 0.4) return 'text-warning';
    return 'text-red-400';
  };

  return (
    <ProtectedRoute requiredTier="starter">
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Header */}
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <Link
              href="/"
              className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
            >
              [DASHBOARD]
            </Link>
          </div>
        </header>

        {/* Content */}
        <div className="max-w-6xl mx-auto px-4 py-8">
          {/* Title and Actions */}
          <div className="flex items-center justify-between mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)]">
              A/B TESTING LABORATORY
            </h1>
            <div className="flex gap-3">
              {viewMode !== 'list' && (
                <button
                  onClick={() => {
                    setViewMode('list');
                    setSelectedTest(null);
                  }}
                  className="font-theme-data text-xs px-4 py-2 border border-[var(--acid-cyan)]/50 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
                >
                  [BACK TO LIST]
                </button>
              )}
              {viewMode === 'list' && (
                <button
                  onClick={() => setViewMode('create')}
                  className="font-theme-data text-xs px-4 py-2 border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
                >
                  [NEW TEST]
                </button>
              )}
            </div>
          </div>

          {error && (
            <div className="mb-6 p-4 border border-warning/50 bg-warning/10 text-warning text-sm font-theme-data">
              {error}
              <button onClick={() => setError(null)} className="ml-4 text-xs underline">
                Dismiss
              </button>
            </div>
          )}

          {/* Create View */}
          {viewMode === 'create' && (
            <div className="border border-[var(--accent)]/30 bg-surface/30 p-6 max-w-xl">
              <h2 className="text-lg font-theme-data text-[var(--acid-cyan)] mb-6">
                CREATE NEW A/B TEST
              </h2>

              {createError && (
                <div className="mb-4 p-3 border border-warning/50 bg-warning/10 text-warning text-sm font-theme-data">
                  {createError}
                </div>
              )}

              <form onSubmit={handleCreateTest} className="space-y-4">
                <div>
                  <label className="block text-xs font-theme-data text-text-muted mb-1">
                    AGENT NAME
                  </label>
                  <input
                    type="text"
                    value={createForm.agent}
                    onChange={(e) => setCreateForm({ ...createForm, agent: e.target.value })}
                    required
                    placeholder="e.g., claude-3-opus"
                    className="w-full bg-bg border border-[var(--accent)]/30 px-3 py-2 font-theme-data text-sm text-text placeholder:text-text-muted/50 focus:border-[var(--accent)] focus:outline-none"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-theme-data text-text-muted mb-1">
                      BASELINE VERSION
                    </label>
                    <input
                      type="number"
                      value={createForm.baseline_version}
                      onChange={(e) =>
                        setCreateForm({ ...createForm, baseline_version: e.target.value })
                      }
                      required
                      min="1"
                      placeholder="e.g., 1"
                      className="w-full bg-bg border border-[var(--accent)]/30 px-3 py-2 font-theme-data text-sm text-text placeholder:text-text-muted/50 focus:border-[var(--accent)] focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-theme-data text-text-muted mb-1">
                      EVOLVED VERSION
                    </label>
                    <input
                      type="number"
                      value={createForm.evolved_version}
                      onChange={(e) =>
                        setCreateForm({ ...createForm, evolved_version: e.target.value })
                      }
                      required
                      min="1"
                      placeholder="e.g., 2"
                      className="w-full bg-bg border border-[var(--accent)]/30 px-3 py-2 font-theme-data text-sm text-text placeholder:text-text-muted/50 focus:border-[var(--accent)] focus:outline-none"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-theme-data text-text-muted mb-1">
                    DESCRIPTION (OPTIONAL)
                  </label>
                  <textarea
                    value={createForm.description}
                    onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
                    placeholder="What changes are being tested?"
                    rows={3}
                    className="w-full bg-bg border border-[var(--accent)]/30 px-3 py-2 font-theme-data text-sm text-text placeholder:text-text-muted/50 focus:border-[var(--accent)] focus:outline-none resize-none"
                  />
                </div>

                <button
                  type="submit"
                  disabled={createLoading}
                  className="w-full py-3 font-theme-data text-sm bg-[var(--accent)]/10 border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/20 transition-colors disabled:opacity-50"
                >
                  {createLoading ? 'CREATING...' : 'START A/B TEST'}
                </button>
              </form>
            </div>
          )}

          {/* List View */}
          {viewMode === 'list' && (
            <>
              {/* Filters */}
              <div className="flex gap-4 mb-6">
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  aria-label="Filter by status"
                  className="bg-bg border border-[var(--accent)]/30 px-3 py-2 font-theme-data text-sm text-text focus:border-[var(--accent)] focus:outline-none"
                >
                  <option value="">All Statuses</option>
                  <option value="active">Active</option>
                  <option value="concluded">Concluded</option>
                  <option value="cancelled">Cancelled</option>
                </select>

                <input
                  type="text"
                  value={agentFilter}
                  onChange={(e) => setAgentFilter(e.target.value)}
                  placeholder="Filter by agent..."
                  aria-label="Filter by agent"
                  className="bg-bg border border-[var(--accent)]/30 px-3 py-2 font-theme-data text-sm text-text placeholder:text-text-muted/50 focus:border-[var(--accent)] focus:outline-none flex-1 max-w-xs"
                />

                <button
                  onClick={fetchTests}
                  className="px-4 py-2 font-theme-data text-xs border border-[var(--acid-cyan)]/50 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
                >
                  [REFRESH]
                </button>
              </div>

              {/* Tests Table */}
              {loading ? (
                <div className="text-center py-12 font-theme-data text-text-muted">
                  Loading A/B tests...
                </div>
              ) : tests.length === 0 ? (
                <div className="text-center py-12 border border-[var(--accent)]/20 bg-surface/20">
                  <div className="font-theme-data text-text-muted mb-4">No A/B tests found</div>
                  <button
                    onClick={() => setViewMode('create')}
                    className="font-theme-data text-xs text-[var(--accent)] hover:underline"
                  >
                    [CREATE YOUR FIRST TEST]
                  </button>
                </div>
              ) : (
                <div className="border border-[var(--accent)]/30 bg-surface/20 overflow-x-auto">
                  <table className="w-full font-theme-data text-sm">
                    <thead>
                      <tr className="border-b border-[var(--accent)]/20 bg-surface/30">
                        <th className="text-left px-4 py-3 text-text-muted">Agent</th>
                        <th className="text-left px-4 py-3 text-text-muted">Versions</th>
                        <th className="text-left px-4 py-3 text-text-muted">Status</th>
                        <th className="text-right px-4 py-3 text-text-muted">Debates</th>
                        <th className="text-right px-4 py-3 text-text-muted">Evolved Win Rate</th>
                        <th className="text-right px-4 py-3 text-text-muted">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tests.map((test) => (
                        <tr
                          key={test.id}
                          className="border-b border-[var(--accent)]/10 hover:bg-[var(--accent)]/5 cursor-pointer"
                          onClick={() => viewTestDetail(test)}
                        >
                          <td className="px-4 py-3 text-[var(--acid-cyan)]">{test.agent}</td>
                          <td className="px-4 py-3 text-text-muted">
                            v{test.baseline_prompt_version} vs v{test.evolved_prompt_version}
                          </td>
                          <td className="px-4 py-3">{getStatusBadge(test.status)}</td>
                          <td className="px-4 py-3 text-right text-text">
                            {test.total_debates}
                            {test.is_significant && (
                              <span
                                className="ml-2 text-[var(--accent)]"
                                title="Statistically significant"
                              >
                                *
                              </span>
                            )}
                          </td>
                          <td
                            className={`px-4 py-3 text-right ${getWinRateColor(test.evolved_win_rate)}`}
                          >
                            {(test.evolved_win_rate * 100).toFixed(1)}%
                          </td>
                          <td className="px-4 py-3 text-right">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                viewTestDetail(test);
                              }}
                              className="text-[var(--acid-cyan)] hover:text-[var(--accent)] text-xs"
                            >
                              [VIEW]
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div className="mt-4 text-xs font-theme-data text-text-muted">
                * Statistically significant (20+ samples, {'>'}10% difference)
              </div>
            </>
          )}

          {/* Detail View */}
          {viewMode === 'detail' && selectedTest && (
            <div className="space-y-6">
              {/* Test Header */}
              <div className="border border-[var(--accent)]/30 bg-surface/30 p-6">
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h2 className="text-xl font-theme-data text-[var(--acid-cyan)] mb-2">
                      {selectedTest.agent}
                    </h2>
                    <div className="text-sm font-theme-data text-text-muted">
                      Test ID: {selectedTest.id.slice(0, 8)}...
                    </div>
                  </div>
                  <div>{getStatusBadge(selectedTest.status)}</div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6">
                  <div>
                    <div className="text-xs font-theme-data text-text-muted mb-1">
                      BASELINE VERSION
                    </div>
                    <div className="text-lg font-theme-data text-text">
                      v{selectedTest.baseline_prompt_version}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs font-theme-data text-text-muted mb-1">
                      EVOLVED VERSION
                    </div>
                    <div className="text-lg font-theme-data text-[var(--accent)]">
                      v{selectedTest.evolved_prompt_version}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs font-theme-data text-text-muted mb-1">STARTED</div>
                    <div className="text-sm font-theme-data text-text">
                      {new Date(selectedTest.started_at).toLocaleDateString()}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs font-theme-data text-text-muted mb-1">SIGNIFICANCE</div>
                    <div
                      className={`text-sm font-theme-data ${selectedTest.is_significant ? 'text-[var(--accent)]' : 'text-text-muted'}`}
                    >
                      {selectedTest.is_significant ? 'SIGNIFICANT' : 'NOT SIGNIFICANT'}
                    </div>
                  </div>
                </div>
              </div>

              {/* Results Comparison */}
              <div className="grid md:grid-cols-2 gap-6">
                {/* Baseline Stats */}
                <div className="border border-[var(--acid-cyan)]/30 bg-surface/20 p-6">
                  <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-4">
                    BASELINE (v{selectedTest.baseline_prompt_version})
                  </h3>
                  <div className="space-y-4">
                    <div>
                      <div className="text-xs font-theme-data text-text-muted mb-1">WIN RATE</div>
                      <div
                        className={`text-3xl font-theme-data ${getWinRateColor(selectedTest.baseline_win_rate)}`}
                      >
                        {(selectedTest.baseline_win_rate * 100).toFixed(1)}%
                      </div>
                    </div>
                    <div className="flex justify-between text-sm font-theme-data">
                      <span className="text-text-muted">Wins</span>
                      <span className="text-text">{selectedTest.baseline_wins}</span>
                    </div>
                    <div className="flex justify-between text-sm font-theme-data">
                      <span className="text-text-muted">Debates</span>
                      <span className="text-text">{selectedTest.baseline_debates}</span>
                    </div>
                  </div>
                </div>

                {/* Evolved Stats */}
                <div className="border border-[var(--accent)]/30 bg-surface/20 p-6">
                  <h3 className="text-sm font-theme-data text-[var(--accent)] mb-4">
                    EVOLVED (v{selectedTest.evolved_prompt_version})
                  </h3>
                  <div className="space-y-4">
                    <div>
                      <div className="text-xs font-theme-data text-text-muted mb-1">WIN RATE</div>
                      <div
                        className={`text-3xl font-theme-data ${getWinRateColor(selectedTest.evolved_win_rate)}`}
                      >
                        {(selectedTest.evolved_win_rate * 100).toFixed(1)}%
                      </div>
                    </div>
                    <div className="flex justify-between text-sm font-theme-data">
                      <span className="text-text-muted">Wins</span>
                      <span className="text-text">{selectedTest.evolved_wins}</span>
                    </div>
                    <div className="flex justify-between text-sm font-theme-data">
                      <span className="text-text-muted">Debates</span>
                      <span className="text-text">{selectedTest.evolved_debates}</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Win Rate Comparison Bar */}
              <div className="border border-[var(--accent)]/30 bg-surface/20 p-6">
                <h3 className="text-sm font-theme-data text-text-muted mb-4">
                  WIN RATE COMPARISON
                </h3>
                <div className="h-8 bg-surface border border-[var(--accent)]/20 flex overflow-hidden">
                  <div
                    className="bg-[var(--acid-cyan)]/50 flex items-center justify-center"
                    style={{ width: `${selectedTest.baseline_win_rate * 100}%` }}
                  >
                    {selectedTest.baseline_win_rate > 0.15 && (
                      <span className="text-xs font-theme-data text-bg">BASELINE</span>
                    )}
                  </div>
                  <div
                    className="bg-[var(--accent)]/50 flex items-center justify-center"
                    style={{ width: `${selectedTest.evolved_win_rate * 100}%` }}
                  >
                    {selectedTest.evolved_win_rate > 0.15 && (
                      <span className="text-xs font-theme-data text-bg">EVOLVED</span>
                    )}
                  </div>
                </div>
                <div className="flex justify-between mt-2 text-xs font-theme-data text-text-muted">
                  <span>Total sample size: {selectedTest.sample_size}</span>
                  <span>Total debates: {selectedTest.total_debates}</span>
                </div>
              </div>

              {/* Actions */}
              {selectedTest.status === 'active' && (
                <div className="flex gap-4">
                  <button
                    onClick={() => handleConcludeTest(selectedTest.id)}
                    className="flex-1 py-3 font-theme-data text-sm bg-[var(--accent)]/10 border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/20 transition-colors"
                  >
                    CONCLUDE TEST
                  </button>
                  <button
                    onClick={() => handleCancelTest(selectedTest.id)}
                    className="py-3 px-6 font-theme-data text-sm border border-warning/50 text-warning hover:bg-warning/10 transition-colors"
                  >
                    CANCEL
                  </button>
                </div>
              )}

              {/* Metadata */}
              {selectedTest.metadata && Object.keys(selectedTest.metadata).length > 0 && (
                <div className="border border-[var(--accent)]/30 bg-surface/20 p-6">
                  <h3 className="text-sm font-theme-data text-text-muted mb-4">METADATA</h3>
                  <pre className="text-xs font-theme-data text-text overflow-x-auto">
                    {JSON.stringify(selectedTest.metadata, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      </main>
    </ProtectedRoute>
  );
}
