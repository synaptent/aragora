'use client';

import { useState, useEffect, useCallback } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { ConsensusKnowledgeBase } from '@/components/ConsensusKnowledgeBase';
import { ConsensusQualityDashboard } from '@/components/ConsensusQualityDashboard';
import { logger } from '@/utils/logger';

interface ConsensusStats {
  total_topics: number;
  high_confidence_count: number;
  domains: string[];
  avg_confidence: number;
  total_dissents: number;
  by_strength: Record<string, number>;
  by_domain: Record<string, number>;
}

interface ContrarianView {
  agent: string;
  position: string;
  confidence: number;
  reasoning: string;
  debate_id: string;
}

interface RiskWarning {
  domain: string;
  risk_type: string;
  severity: string;
  description: string;
  mitigation: string | null;
  detected_at: string;
}

type TabType = 'overview' | 'contrarian' | 'risks' | 'domains';

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  high: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  medium: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  low: 'bg-text-muted/20 text-text-muted border-text-muted/30',
};

export default function ConsensusPage() {
  const { config: backendConfig } = useBackend();
  const [activeTab, setActiveTab] = useState<TabType>('overview');

  // Stats
  const [stats, setStats] = useState<ConsensusStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);

  // Contrarian views
  const [contrarianViews, setContrarianViews] = useState<ContrarianView[]>([]);
  const [contrarianLoading, setContrarianLoading] = useState(false);

  // Risk warnings
  const [riskWarnings, setRiskWarnings] = useState<RiskWarning[]>([]);
  const [risksLoading, setRisksLoading] = useState(false);

  // Domain history
  const [selectedDomain, setSelectedDomain] = useState<string>('');
  const [domainHistory, setDomainHistory] = useState<Record<string, unknown>[]>([]);
  const [domainLoading, setDomainLoading] = useState(false);

  const fetchStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const res = await fetch(`${backendConfig.api}/api/consensus/stats`);
      if (res.ok) {
        const data = await res.json();
        setStats(data);
      }
    } catch (err) {
      logger.error('Failed to fetch consensus stats:', err);
    } finally {
      setStatsLoading(false);
    }
  }, [backendConfig.api]);

  const fetchContrarianViews = useCallback(async () => {
    setContrarianLoading(true);
    try {
      const res = await fetch(`${backendConfig.api}/api/consensus/contrarian-views?limit=20`);
      if (res.ok) {
        const data = await res.json();
        setContrarianViews(data.views || []);
      }
    } catch (err) {
      logger.error('Failed to fetch contrarian views:', err);
    } finally {
      setContrarianLoading(false);
    }
  }, [backendConfig.api]);

  const fetchRiskWarnings = useCallback(async () => {
    setRisksLoading(true);
    try {
      const res = await fetch(`${backendConfig.api}/api/consensus/risk-warnings?limit=20`);
      if (res.ok) {
        const data = await res.json();
        setRiskWarnings(data.warnings || []);
      }
    } catch (err) {
      logger.error('Failed to fetch risk warnings:', err);
    } finally {
      setRisksLoading(false);
    }
  }, [backendConfig.api]);

  const fetchDomainHistory = useCallback(
    async (domain: string) => {
      if (!domain) return;
      setDomainLoading(true);
      try {
        const res = await fetch(
          `${backendConfig.api}/api/consensus/domain/${encodeURIComponent(domain)}?limit=50`,
        );
        if (res.ok) {
          const data = await res.json();
          setDomainHistory(data.history || []);
        }
      } catch (err) {
        logger.error('Failed to fetch domain history:', err);
      } finally {
        setDomainLoading(false);
      }
    },
    [backendConfig.api],
  );

  // Load stats on mount
  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  // Load tab data when switching
  useEffect(() => {
    if (activeTab === 'contrarian') fetchContrarianViews();
    if (activeTab === 'risks') fetchRiskWarnings();
  }, [activeTab, fetchContrarianViews, fetchRiskWarnings]);

  // Load domain history when selected
  useEffect(() => {
    if (selectedDomain && activeTab === 'domains') {
      fetchDomainHistory(selectedDomain);
    }
  }, [selectedDomain, activeTab, fetchDomainHistory]);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Title */}
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              {'>'} CONSENSUS MEMORY
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Institutional knowledge from debate outcomes. Settled topics, dissenting views, risk
              warnings, and domain history.
            </p>
          </div>

          {/* Stats Overview */}
          {stats && (
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
              <div className="p-3 border border-[var(--accent)]/30 rounded bg-surface/30 text-center">
                <div className="text-2xl font-theme-data text-[var(--accent)]">
                  {stats.total_topics}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Topics</div>
              </div>
              <div className="p-3 border border-[var(--accent)]/30 rounded bg-surface/30 text-center">
                <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                  {stats.high_confidence_count}
                </div>
                <div className="text-xs font-theme-data text-text-muted">High Confidence</div>
              </div>
              <div className="p-3 border border-[var(--accent)]/30 rounded bg-surface/30 text-center">
                <div className="text-2xl font-theme-data text-text">
                  {(stats.avg_confidence * 100).toFixed(0)}%
                </div>
                <div className="text-xs font-theme-data text-text-muted">Avg Confidence</div>
              </div>
              <div className="p-3 border border-[var(--accent)]/30 rounded bg-surface/30 text-center">
                <div className="text-2xl font-theme-data text-warning">{stats.total_dissents}</div>
                <div className="text-xs font-theme-data text-text-muted">Dissents</div>
              </div>
              <div className="p-3 border border-[var(--accent)]/30 rounded bg-surface/30 text-center">
                <div className="text-2xl font-theme-data text-acid-purple">
                  {stats.domains.length}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Domains</div>
              </div>
            </div>
          )}
          {statsLoading && !stats && (
            <div className="text-center py-4 text-[var(--accent)] font-theme-data animate-pulse mb-6">
              Loading stats...
            </div>
          )}

          {/* Tab Navigation */}
          <div className="flex gap-2 mb-6">
            {[
              { id: 'overview' as const, label: 'OVERVIEW' },
              { id: 'contrarian' as const, label: 'CONTRARIAN VIEWS' },
              { id: 'risks' as const, label: 'RISK WARNINGS' },
              { id: 'domains' as const, label: 'BY DOMAIN' },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                  activeTab === tab.id
                    ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                    : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
                }`}
              >
                [{tab.label}]
              </button>
            ))}
          </div>

          {/* Overview Tab */}
          {activeTab === 'overview' && (
            <div className="grid gap-6 lg:grid-cols-2">
              <PanelErrorBoundary panelName="Consensus Knowledge Base">
                <ConsensusKnowledgeBase apiBase={backendConfig.api} />
              </PanelErrorBoundary>

              <PanelErrorBoundary panelName="Consensus Quality">
                <ConsensusQualityDashboard apiBase={backendConfig.api} />
              </PanelErrorBoundary>

              {/* Strength Distribution */}
              {stats?.by_strength && Object.keys(stats.by_strength).length > 0 && (
                <div className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30">
                  <h3 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-3">
                    Consensus Strength Distribution
                  </h3>
                  <div className="space-y-2">
                    {Object.entries(stats.by_strength)
                      .sort(([, a], [, b]) => b - a)
                      .map(([strength, count]) => (
                        <div key={strength} className="flex items-center gap-3">
                          <span className="text-xs font-theme-data text-text w-24 capitalize">
                            {strength}
                          </span>
                          <div className="flex-1 h-4 bg-bg rounded overflow-hidden">
                            <div
                              className="h-full bg-[var(--accent)]/40 rounded"
                              style={{
                                width: `${Math.min(100, (count / stats.total_topics) * 100)}%`,
                              }}
                            />
                          </div>
                          <span className="text-xs font-theme-data text-text-muted w-8 text-right">
                            {count}
                          </span>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {/* Domain Distribution */}
              {stats?.by_domain && Object.keys(stats.by_domain).length > 0 && (
                <div className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30">
                  <h3 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-3">
                    Domain Distribution
                  </h3>
                  <div className="grid grid-cols-2 gap-2">
                    {Object.entries(stats.by_domain)
                      .sort(([, a], [, b]) => b - a)
                      .map(([domain, count]) => (
                        <button
                          key={domain}
                          onClick={() => {
                            setSelectedDomain(domain);
                            setActiveTab('domains');
                          }}
                          className="flex items-center justify-between p-2 bg-bg/50 rounded hover:bg-[var(--accent)]/10 transition-colors"
                        >
                          <span className="text-xs font-theme-data text-text">{domain}</span>
                          <span className="text-xs font-theme-data text-[var(--accent)]">
                            {count}
                          </span>
                        </button>
                      ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Contrarian Views Tab */}
          {activeTab === 'contrarian' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="font-theme-data text-text">Contrarian Perspectives</h2>
                  <p className="text-text-muted font-theme-data text-xs mt-1">
                    Dissenting views from agents who disagreed with the majority. These perspectives
                    often reveal blind spots.
                  </p>
                </div>
                <button
                  onClick={fetchContrarianViews}
                  disabled={contrarianLoading}
                  className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] transition-colors disabled:opacity-50"
                >
                  {contrarianLoading ? '[LOADING...]' : '[REFRESH]'}
                </button>
              </div>

              {contrarianLoading ? (
                <div className="text-center py-8 text-[var(--accent)] font-theme-data animate-pulse">
                  Loading contrarian views...
                </div>
              ) : contrarianViews.length === 0 ? (
                <div className="p-8 border border-[var(--accent)]/20 rounded text-center">
                  <p className="font-theme-data text-text-muted">
                    No contrarian views recorded yet.
                  </p>
                  <p className="font-theme-data text-text-muted/60 text-xs mt-2">
                    Run some debates to build institutional dissent memory.
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  {contrarianViews.map((view, idx) => (
                    <div
                      key={idx}
                      className="p-4 border border-orange-500/20 rounded bg-orange-900/5 hover:border-orange-500/40 transition-colors"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1 min-w-0">
                          <p className="font-theme-data text-sm text-text">{view.position}</p>
                          {view.reasoning && (
                            <p className="font-theme-data text-xs text-text-muted mt-2 italic">
                              &quot;{view.reasoning}&quot;
                            </p>
                          )}
                          <div className="flex items-center gap-3 mt-2 text-xs font-theme-data text-text-muted">
                            <span>
                              Agent: <span className="text-orange-400">{view.agent}</span>
                            </span>
                            <span>|</span>
                            <span>
                              Confidence:{' '}
                              <span className="text-[var(--acid-cyan)]">
                                {(view.confidence * 100).toFixed(0)}%
                              </span>
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Risk Warnings Tab */}
          {activeTab === 'risks' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="font-theme-data text-text">Risk Warnings</h2>
                  <p className="text-text-muted font-theme-data text-xs mt-1">
                    Edge cases and risk factors flagged during debate analysis.
                  </p>
                </div>
                <button
                  onClick={fetchRiskWarnings}
                  disabled={risksLoading}
                  className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] transition-colors disabled:opacity-50"
                >
                  {risksLoading ? '[LOADING...]' : '[REFRESH]'}
                </button>
              </div>

              {risksLoading ? (
                <div className="text-center py-8 text-[var(--accent)] font-theme-data animate-pulse">
                  Loading risk warnings...
                </div>
              ) : riskWarnings.length === 0 ? (
                <div className="p-8 border border-[var(--accent)]/20 rounded text-center">
                  <p className="font-theme-data text-text-muted">No risk warnings recorded yet.</p>
                  <p className="font-theme-data text-text-muted/60 text-xs mt-2">
                    Agents flag risks during debates automatically.
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  {riskWarnings.map((warning, idx) => (
                    <div
                      key={idx}
                      className={`p-4 border rounded ${SEVERITY_COLORS[warning.severity] || SEVERITY_COLORS.low}`}
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-2">
                            <span className="text-xs font-theme-data px-2 py-0.5 rounded bg-surface uppercase">
                              {warning.risk_type}
                            </span>
                            <span className="text-xs font-theme-data px-2 py-0.5 rounded bg-surface uppercase">
                              {warning.severity}
                            </span>
                            <span className="text-xs font-theme-data text-text-muted">
                              {warning.domain}
                            </span>
                          </div>
                          <p className="font-theme-data text-sm text-text">{warning.description}</p>
                          {warning.mitigation && (
                            <div className="mt-2 p-2 bg-surface/50 rounded">
                              <span className="text-xs font-theme-data text-[var(--accent)]">
                                Mitigation:{' '}
                              </span>
                              <span className="text-xs font-theme-data text-text-muted">
                                {warning.mitigation}
                              </span>
                            </div>
                          )}
                          <div className="text-xs font-theme-data text-text-muted/50 mt-2">
                            {new Date(warning.detected_at).toLocaleString()}
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Domain History Tab */}
          {activeTab === 'domains' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <h2 className="font-theme-data text-text">Domain History</h2>
                {selectedDomain && (
                  <button
                    onClick={() => fetchDomainHistory(selectedDomain)}
                    disabled={domainLoading}
                    className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] transition-colors disabled:opacity-50"
                  >
                    {domainLoading ? '[LOADING...]' : '[REFRESH]'}
                  </button>
                )}
              </div>

              {/* Domain selector */}
              {stats?.domains && stats.domains.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {stats.domains.map((domain) => (
                    <button
                      key={domain}
                      onClick={() => setSelectedDomain(domain)}
                      className={`px-3 py-2 border rounded font-theme-data text-sm transition-colors ${
                        selectedDomain === domain
                          ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                          : 'border-[var(--accent)]/20 text-text-muted hover:border-[var(--accent)]/40'
                      }`}
                    >
                      {domain}
                      {stats.by_domain[domain] && (
                        <span className="ml-2 text-xs text-text-muted">
                          ({stats.by_domain[domain]})
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              ) : (
                <div className="p-8 border border-[var(--accent)]/20 rounded text-center">
                  <p className="font-theme-data text-text-muted">
                    No domains found. Run debates with domain tags to populate.
                  </p>
                </div>
              )}

              {/* Domain results */}
              {selectedDomain && (
                <>
                  {domainLoading ? (
                    <div className="text-center py-8 text-[var(--accent)] font-theme-data animate-pulse">
                      Loading {selectedDomain} history...
                    </div>
                  ) : domainHistory.length === 0 ? (
                    <div className="p-8 border border-[var(--accent)]/20 rounded text-center">
                      <p className="font-theme-data text-text-muted">
                        No consensus history for {selectedDomain}.
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {domainHistory.map((record, idx) => (
                        <div
                          key={idx}
                          className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30"
                        >
                          <div className="flex items-start justify-between gap-4">
                            <div className="flex-1 min-w-0">
                              <div className="font-theme-data text-sm text-[var(--acid-cyan)]">
                                {(record as Record<string, string>).topic || 'Unknown topic'}
                              </div>
                              <p className="font-theme-data text-xs text-text mt-1">
                                {(record as Record<string, string>).conclusion || ''}
                              </p>
                              <div className="flex items-center gap-3 mt-2 text-xs font-theme-data text-text-muted">
                                {(record as Record<string, number>).confidence !== undefined && (
                                  <span>
                                    Confidence:{' '}
                                    {((record as Record<string, number>).confidence * 100).toFixed(
                                      0,
                                    )}
                                    %
                                  </span>
                                )}
                                {(record as Record<string, string>).strength && (
                                  <>
                                    <span>|</span>
                                    <span>
                                      Strength: {(record as Record<string, string>).strength}
                                    </span>
                                  </>
                                )}
                                {(record as Record<string, string>).timestamp && (
                                  <>
                                    <span>|</span>
                                    <span>
                                      {new Date(
                                        (record as Record<string, string>).timestamp,
                                      ).toLocaleDateString()}
                                    </span>
                                  </>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // CONSENSUS MEMORY</p>
        </footer>
      </main>
    </>
  );
}
