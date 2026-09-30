'use client';

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { ErrorWithRetry } from './RetryButton';
import { withErrorBoundary } from './PanelErrorBoundary';
import { fetchWithRetry } from '@/utils/retry';
import type { StreamEvent } from '@/types/events';
import { API_BASE_URL } from '@/config';
import { useAuth } from '@/context/AuthContext';

interface EmergentTrait {
  agent: string;
  trait: string;
  domain: string;
  confidence: number;
  evidence: string[];
  detected_at: string;
}

interface CrossPollination {
  source_agent: string;
  target_agent: string;
  trait: string;
  expected_improvement: number;
  rationale: string;
}

interface GenesisStats {
  total_events: number;
  total_births: number;
  total_deaths: number;
  net_population_change: number;
  avg_fitness_change_recent: number;
  integrity_verified: boolean;
  event_counts: Record<string, number>;
}

interface CritiquePattern {
  pattern: string;
  issue_type: string;
  suggested_rebuttal: string;
  success_rate: number;
  usage_count: number;
}

interface LaboratoryPanelProps {
  apiBase?: string;
  events?: StreamEvent[];
}

const DEFAULT_API_BASE = API_BASE_URL;

function LaboratoryPanelComponent({
  apiBase = DEFAULT_API_BASE,
  events = [],
}: LaboratoryPanelProps) {
  const { tokens, isAuthenticated, isLoading: authLoading } = useAuth();
  const [apiTraits, setApiTraits] = useState<EmergentTrait[]>([]);
  const [pollinations, setPollinations] = useState<CrossPollination[]>([]);
  const [genesisStats, setGenesisStats] = useState<GenesisStats | null>(null);
  const [patterns, setPatterns] = useState<CritiquePattern[]>([]);
  const [loading, setLoading] = useState(true);

  // Extract trait_emerged events from stream
  const eventTraits = useMemo(
    () =>
      events
        .filter((e) => e.type === 'trait_emerged')
        .map((e) => ({
          agent: (e.data as { agent?: string }).agent || 'unknown',
          trait: (e.data as { trait?: string }).trait || '',
          domain: (e.data as { domain?: string }).domain || 'general',
          confidence: (e.data as { confidence?: number }).confidence || 0.5,
          evidence: (e.data as { evidence?: string[] }).evidence || [],
          detected_at: new Date(e.timestamp * 1000).toISOString(),
        })),
    [events],
  );

  // Merge API traits with event traits (events are more recent)
  const traits = useMemo(() => {
    // Create a Set of event trait identifiers to deduplicate
    const eventKeys = new Set(eventTraits.map((t) => `${t.agent}:${t.trait}`));
    // Keep API traits not superseded by events, then add event traits
    return [...eventTraits, ...apiTraits.filter((t) => !eventKeys.has(`${t.agent}:${t.trait}`))];
  }, [apiTraits, eventTraits]);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'traits' | 'pollinations' | 'evolution' | 'patterns'>(
    'traits',
  );
  const [expanded, setExpanded] = useState(true); // Show by default

  const fetchData = useCallback(async () => {
    // Skip API calls if not authenticated
    if (!isAuthenticated || authLoading) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    // Build auth headers
    const headers: HeadersInit = { 'Content-Type': 'application/json' };
    if (tokens?.access_token) {
      headers['Authorization'] = `Bearer ${tokens.access_token}`;
    }

    // Use allSettled to handle partial failures gracefully
    const results = await Promise.allSettled([
      fetchWithRetry(
        `${apiBase}/api/laboratory/emergent-traits?min_confidence=0.3&limit=10`,
        { headers },
        { maxRetries: 2 },
      ),
      fetchWithRetry(
        `${apiBase}/api/laboratory/cross-pollinations/suggest`,
        { headers },
        { maxRetries: 2 },
      ),
      fetchWithRetry(`${apiBase}/api/genesis/stats`, { headers }, { maxRetries: 2 }),
      fetchWithRetry(
        `${apiBase}/api/critiques/patterns?limit=15&min_success=0.5`,
        { headers },
        { maxRetries: 2 },
      ),
    ]);

    const [traitsResult, pollinationsResult, genesisResult, patternsResult] = results;
    let hasError = false;

    if (traitsResult.status === 'fulfilled' && traitsResult.value.ok) {
      const data = await traitsResult.value.json();
      setApiTraits(data.emergent_traits || []);
    } else {
      hasError = true;
    }

    if (pollinationsResult.status === 'fulfilled' && pollinationsResult.value.ok) {
      const data = await pollinationsResult.value.json();
      setPollinations(data.suggestions || []);
    } else {
      hasError = true;
    }

    if (genesisResult.status === 'fulfilled' && genesisResult.value.ok) {
      const data = await genesisResult.value.json();
      setGenesisStats(data);
    } else {
      hasError = true;
    }

    if (patternsResult.status === 'fulfilled' && patternsResult.value.ok) {
      const data = await patternsResult.value.json();
      setPatterns(data.patterns || []);
    } else {
      hasError = true;
    }

    if (hasError) {
      setError('Some data failed to load. Partial results shown.');
    }
    setLoading(false);
  }, [apiBase, tokens?.access_token, isAuthenticated, authLoading]);

  // Use ref to store latest fetchData to avoid interval recreation
  const fetchDataRef = useRef(fetchData);
  fetchDataRef.current = fetchData;

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Separate effect for interval - runs once, uses ref
  useEffect(() => {
    const interval = setInterval(() => {
      fetchDataRef.current();
    }, 300000);
    return () => clearInterval(interval);
  }, []); // Empty deps - interval created once

  const getConfidenceColor = (confidence: number): string => {
    if (confidence >= 0.8) return 'text-green-400';
    if (confidence >= 0.5) return 'text-yellow-400';
    return 'text-orange-400';
  };

  const getDomainColor = (domain: string): string => {
    const colors: Record<string, string> = {
      technical: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
      ethics: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
      creative: 'bg-pink-500/20 text-pink-400 border-pink-500/30',
      analytical: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
      general: 'bg-zinc-500/20 text-zinc-500 dark:text-zinc-400 border-zinc-500/30',
    };
    return colors[domain] || colors.general;
  };

  return (
    <div className="bg-surface border border-border rounded-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-text font-theme-data">Persona Laboratory</h3>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchData}
            disabled={loading}
            aria-label="Refresh laboratory data"
            className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] disabled:opacity-50"
          >
            [REFRESH]
          </button>
          <button
            onClick={() => setExpanded(!expanded)}
            aria-expanded={expanded}
            aria-label={expanded ? 'Collapse laboratory panel' : 'Expand laboratory panel'}
            className="text-xs font-theme-data text-text-muted hover:text-text"
          >
            [{expanded ? '-' : '+'}]
          </button>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="flex items-center gap-4 text-xs font-theme-data text-text-muted mb-4 border-b border-border pb-3 flex-wrap">
        <span>
          Traits: <span className="text-[var(--acid-cyan)]">{traits.length}</span>
        </span>
        <span>
          Pollinations: <span className="text-[var(--accent)]">{pollinations.length}</span>
        </span>
        <span>
          Patterns: <span className="text-purple-400">{patterns.length}</span>
        </span>
        {genesisStats && (
          <>
            <span>
              Population:{' '}
              <span
                className={
                  genesisStats.net_population_change >= 0 ? 'text-green-400' : 'text-red-400'
                }
              >
                {genesisStats.net_population_change >= 0 ? '+' : ''}
                {genesisStats.net_population_change}
              </span>
            </span>
            <span>
              Events: <span className="text-yellow-400">{genesisStats.total_events}</span>
            </span>
          </>
        )}
      </div>

      {error && <ErrorWithRetry error={error} onRetry={fetchData} className="mb-4" />}

      {expanded && (
        <>
          {/* Tab Navigation */}
          <div
            role="tablist"
            aria-label="Laboratory sections"
            className="flex space-x-1 bg-bg border border-border rounded p-1 mb-4"
          >
            <button
              role="tab"
              id="lab-traits-tab"
              aria-selected={activeTab === 'traits'}
              aria-controls="lab-traits-panel"
              onClick={() => setActiveTab('traits')}
              className={`px-3 py-1 rounded text-sm font-theme-data transition-colors flex-1 ${
                activeTab === 'traits'
                  ? 'bg-[var(--acid-cyan)] text-bg font-medium'
                  : 'text-text-muted hover:text-text'
              }`}
            >
              EMERGENT TRAITS
            </button>
            <button
              role="tab"
              id="lab-pollinations-tab"
              aria-selected={activeTab === 'pollinations'}
              aria-controls="lab-pollinations-panel"
              onClick={() => setActiveTab('pollinations')}
              className={`px-3 py-1 rounded text-sm font-theme-data transition-colors flex-1 ${
                activeTab === 'pollinations'
                  ? 'bg-[var(--accent)] text-bg font-medium'
                  : 'text-text-muted hover:text-text'
              }`}
            >
              POLLINATIONS
            </button>
            <button
              role="tab"
              id="lab-evolution-tab"
              aria-selected={activeTab === 'evolution'}
              aria-controls="lab-evolution-panel"
              onClick={() => setActiveTab('evolution')}
              className={`px-3 py-1 rounded text-sm font-theme-data transition-colors flex-1 ${
                activeTab === 'evolution'
                  ? 'bg-yellow-500 text-bg font-medium'
                  : 'text-text-muted hover:text-text'
              }`}
            >
              EVOLUTION
            </button>
            <button
              role="tab"
              id="lab-patterns-tab"
              aria-selected={activeTab === 'patterns'}
              aria-controls="lab-patterns-panel"
              onClick={() => setActiveTab('patterns')}
              className={`px-3 py-1 rounded text-sm font-theme-data transition-colors flex-1 ${
                activeTab === 'patterns'
                  ? 'bg-purple-500 text-bg font-medium'
                  : 'text-text-muted hover:text-text'
              }`}
            >
              PATTERNS
            </button>
          </div>

          {/* Traits Tab */}
          {activeTab === 'traits' && (
            <div
              id="lab-traits-panel"
              role="tabpanel"
              aria-labelledby="lab-traits-tab"
              className="space-y-3 max-h-80 overflow-y-auto"
            >
              {loading && traits.length === 0 && (
                <div className="text-center text-text-muted py-4 font-theme-data text-sm">
                  Detecting emergent traits...
                </div>
              )}

              {!loading && traits.length === 0 && (
                <div className="text-center text-text-muted py-4 font-theme-data text-sm">
                  No emergent traits detected yet. Run more debates to discover agent
                  specializations.
                </div>
              )}

              {traits.map((trait, index) => (
                <div
                  key={`${trait.agent}-${trait.trait}-${index}`}
                  className="p-3 bg-bg border border-border rounded-lg hover:border-[var(--acid-cyan)]/50 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-theme-data text-[var(--acid-cyan)] font-bold">
                        {trait.agent}
                      </span>
                      <span
                        className={`px-2 py-0.5 text-xs rounded border ${getDomainColor(trait.domain)}`}
                      >
                        {trait.domain}
                      </span>
                    </div>
                    <span
                      className={`text-xs font-theme-data ${getConfidenceColor(trait.confidence)}`}
                    >
                      {(trait.confidence * 100).toFixed(0)}%
                    </span>
                  </div>

                  <p className="text-sm text-text font-medium mb-2">{trait.trait}</p>

                  {trait.evidence && trait.evidence.length > 0 && (
                    <div className="space-y-1">
                      {trait.evidence.slice(0, 2).map((e, i) => (
                        <p key={i} className="text-xs text-text-muted line-clamp-1">
                          {e}
                        </p>
                      ))}
                      {trait.evidence.length > 2 && (
                        <p className="text-xs text-text-muted">
                          +{trait.evidence.length - 2} more evidence
                        </p>
                      )}
                    </div>
                  )}

                  <div className="mt-2 text-xs text-text-muted font-theme-data">
                    Detected: {new Date(trait.detected_at).toLocaleDateString()}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Pollinations Tab */}
          {activeTab === 'pollinations' && (
            <div
              id="lab-pollinations-panel"
              role="tabpanel"
              aria-labelledby="lab-pollinations-tab"
              className="space-y-3 max-h-80 overflow-y-auto"
            >
              {loading && pollinations.length === 0 && (
                <div className="text-center text-text-muted py-4 font-theme-data text-sm">
                  Analyzing cross-pollination opportunities...
                </div>
              )}

              {!loading && pollinations.length === 0 && (
                <div className="text-center text-text-muted py-4 font-theme-data text-sm">
                  No cross-pollination suggestions yet. Lab needs more trait data.
                </div>
              )}

              {pollinations.map((pollination, index) => (
                <div
                  key={`${pollination.source_agent}-${pollination.target_agent}-${index}`}
                  className="p-3 bg-bg border border-border rounded-lg hover:border-[var(--accent)]/50 transition-colors"
                >
                  <div className="flex items-center gap-2 mb-2 font-theme-data text-sm">
                    <span className="text-[var(--acid-cyan)]">{pollination.source_agent}</span>
                    <span className="text-text-muted">-&gt;</span>
                    <span className="text-[var(--accent)]">{pollination.target_agent}</span>
                  </div>

                  <p className="text-sm text-text font-medium mb-1">
                    Transfer: {pollination.trait}
                  </p>

                  <p className="text-xs text-text-muted mb-2">{pollination.rationale}</p>

                  <div className="flex items-center justify-between text-xs font-theme-data">
                    <span className="text-text-muted">Expected improvement:</span>
                    <span className="text-[var(--accent)]">
                      +{(pollination.expected_improvement * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Evolution Tab */}
          {activeTab === 'evolution' && (
            <div
              id="lab-evolution-panel"
              role="tabpanel"
              aria-labelledby="lab-evolution-tab"
              className="space-y-4 max-h-80 overflow-y-auto"
            >
              {loading && !genesisStats && (
                <div className="text-center text-text-muted py-4 font-theme-data text-sm">
                  Loading evolution data...
                </div>
              )}

              {!loading && !genesisStats && (
                <div className="text-center text-text-muted py-4 font-theme-data text-sm">
                  No evolution data available yet.
                </div>
              )}

              {genesisStats && (
                <>
                  {/* Population Stats */}
                  <div className="grid grid-cols-3 gap-3">
                    <div className="p-3 bg-bg border border-border rounded-lg text-center">
                      <div className="text-2xl font-theme-data text-green-400">
                        {genesisStats.total_births}
                      </div>
                      <div className="text-xs text-text-muted">Births</div>
                    </div>
                    <div className="p-3 bg-bg border border-border rounded-lg text-center">
                      <div className="text-2xl font-theme-data text-red-400">
                        {genesisStats.total_deaths}
                      </div>
                      <div className="text-xs text-text-muted">Deaths</div>
                    </div>
                    <div className="p-3 bg-bg border border-border rounded-lg text-center">
                      <div
                        className={`text-2xl font-theme-data ${genesisStats.net_population_change >= 0 ? 'text-green-400' : 'text-red-400'}`}
                      >
                        {genesisStats.net_population_change >= 0 ? '+' : ''}
                        {genesisStats.net_population_change}
                      </div>
                      <div className="text-xs text-text-muted">Net Change</div>
                    </div>
                  </div>

                  {/* Fitness Trend */}
                  <div className="p-3 bg-bg border border-border rounded-lg">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-theme-data text-text-muted">
                        Avg Fitness Change (Recent)
                      </span>
                      <span
                        className={`text-lg font-theme-data ${genesisStats.avg_fitness_change_recent >= 0 ? 'text-green-400' : 'text-red-400'}`}
                      >
                        {genesisStats.avg_fitness_change_recent >= 0 ? '+' : ''}
                        {genesisStats.avg_fitness_change_recent.toFixed(4)}
                      </span>
                    </div>
                    <div className="w-full h-2 bg-surface rounded-full overflow-hidden">
                      <div
                        className={`h-full ${genesisStats.avg_fitness_change_recent >= 0 ? 'bg-green-400' : 'bg-red-400'}`}
                        style={{
                          width: `${Math.min(100, Math.abs(genesisStats.avg_fitness_change_recent) * 500)}%`,
                        }}
                      />
                    </div>
                  </div>

                  {/* Event Breakdown */}
                  {genesisStats.event_counts &&
                    Object.keys(genesisStats.event_counts).length > 0 && (
                      <div className="p-3 bg-bg border border-border rounded-lg">
                        <div className="text-sm font-theme-data text-text-muted mb-3">
                          Event Types
                        </div>
                        <div className="space-y-2">
                          {Object.entries(genesisStats.event_counts)
                            .filter(([_, count]) => count > 0)
                            .sort(([_, a], [__, b]) => b - a)
                            .map(([type, count]) => (
                              <div
                                key={type}
                                className="flex items-center justify-between text-xs font-theme-data"
                              >
                                <span className="text-text-muted">{type.replace(/_/g, ' ')}</span>
                                <span className="text-yellow-400">{count}</span>
                              </div>
                            ))}
                        </div>
                      </div>
                    )}

                  {/* Integrity Status */}
                  <div className="flex items-center justify-between p-2 bg-bg border border-border rounded-lg text-xs font-theme-data">
                    <span className="text-text-muted">Ledger Integrity</span>
                    <span
                      className={
                        genesisStats.integrity_verified ? 'text-green-400' : 'text-red-400'
                      }
                    >
                      {genesisStats.integrity_verified ? 'VERIFIED' : 'UNVERIFIED'}
                    </span>
                  </div>
                </>
              )}
            </div>
          )}

          {/* Patterns Tab */}
          {activeTab === 'patterns' && (
            <div
              id="lab-patterns-panel"
              role="tabpanel"
              aria-labelledby="lab-patterns-tab"
              className="space-y-3 max-h-80 overflow-y-auto"
            >
              {loading && patterns.length === 0 && (
                <div className="text-center text-text-muted py-4 font-theme-data text-sm">
                  Discovering critique patterns...
                </div>
              )}

              {!loading && patterns.length === 0 && (
                <div className="text-center text-text-muted py-4 font-theme-data text-sm">
                  No critique patterns yet. Run more debates to discover effective arguments.
                </div>
              )}

              {patterns.map((pattern, index) => (
                <div
                  key={`${pattern.pattern.slice(0, 20)}-${index}`}
                  className="p-3 bg-bg border border-border rounded-lg hover:border-purple-500/50 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <span
                      className={`px-2 py-0.5 text-xs rounded border bg-purple-500/20 text-purple-400 border-purple-500/30`}
                    >
                      {pattern.issue_type || 'general'}
                    </span>
                    <div className="flex items-center gap-2 text-xs font-theme-data">
                      <span
                        className={
                          pattern.success_rate >= 0.7
                            ? 'text-green-400'
                            : pattern.success_rate >= 0.5
                              ? 'text-yellow-400'
                              : 'text-orange-400'
                        }
                      >
                        {(pattern.success_rate * 100).toFixed(0)}% success
                      </span>
                      <span className="text-text-muted">{pattern.usage_count} uses</span>
                    </div>
                  </div>

                  <p className="text-sm text-text font-medium mb-2">{pattern.pattern}</p>

                  {pattern.suggested_rebuttal && (
                    <div className="text-xs text-text-muted p-2 bg-surface rounded border border-border">
                      <span className="text-purple-400 font-theme-data">Rebuttal:</span>{' '}
                      {pattern.suggested_rebuttal}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* Help text when collapsed */}
      {!expanded && (
        <div className="text-xs font-theme-data text-text-muted">
          <p>
            <span className="text-[var(--acid-cyan)]">Traits:</span> Discovered specializations |{' '}
            <span className="text-[var(--accent)]">Pollinations:</span> Trait transfers |{' '}
            <span className="text-yellow-400">Evolution:</span> Population dynamics
          </p>
        </div>
      )}
    </div>
  );
}

// Wrap with error boundary for graceful error handling
export const LaboratoryPanel = withErrorBoundary(LaboratoryPanelComponent, 'Laboratory');
