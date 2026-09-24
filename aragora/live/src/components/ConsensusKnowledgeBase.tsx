'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { logger } from '@/utils/logger';
import type { StreamEvent } from '@/types/events';

interface SettledTopic {
  topic: string;
  conclusion: string;
  confidence: number;
  strength: number;
  timestamp: string;
}

interface ConsensusStats {
  total_topics: number;
  high_confidence_count: number;
  domains: string[];
  avg_confidence: number;
}

interface SimilarDebate {
  topic: string;
  conclusion: string;
  confidence: number;
  similarity: number;
}

interface DissentView {
  topic: string;
  majority_view: string;
  dissenting_view: string;
  dissenting_agent: string;
  confidence: number;
  reasoning?: string;
}

interface ConsensusKnowledgeBaseProps {
  apiBase: string;
  events?: StreamEvent[];
}

type TabType = 'settled' | 'search' | 'stats' | 'dissents';

export function ConsensusKnowledgeBase({ apiBase, events = [] }: ConsensusKnowledgeBaseProps) {
  const [expanded, setExpanded] = useState(true); // Show by default
  const [activeTab, setActiveTab] = useState<TabType>('settled');
  const [settledTopics, setSettledTopics] = useState<SettledTopic[]>([]);
  const [stats, setStats] = useState<ConsensusStats | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SimilarDebate[]>([]);
  const [dissents, setDissents] = useState<DissentView[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchSettled = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBase}/api/consensus/settled?min_confidence=0.7&limit=15`);
      if (!response.ok) throw new Error('Failed to fetch settled topics');
      const data = await response.json();
      setSettledTopics(data.topics || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  const fetchStats = useCallback(async () => {
    try {
      const response = await fetch(`${apiBase}/api/consensus/stats`);
      if (!response.ok) throw new Error('Failed to fetch stats');
      const data = await response.json();
      setStats(data);
    } catch (err) {
      logger.error('Failed to fetch stats:', err);
    }
  }, [apiBase]);

  const searchSimilar = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `${apiBase}/api/consensus/similar?topic=${encodeURIComponent(searchQuery)}&limit=5`,
      );
      if (!response.ok) throw new Error('Failed to search');
      const data = await response.json();
      setSearchResults(data.similar || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Search failed');
    } finally {
      setLoading(false);
    }
  }, [apiBase, searchQuery]);

  const fetchDissents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBase}/api/consensus/dissents?limit=10`);
      if (!response.ok) throw new Error('Failed to fetch dissents');
      const data = await response.json();
      setDissents(data.dissents || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch dissents');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    if (expanded) {
      fetchSettled();
      fetchStats();
    }
  }, [expanded, fetchSettled, fetchStats]);

  useEffect(() => {
    if (expanded && activeTab === 'dissents') {
      fetchDissents();
    }
  }, [expanded, activeTab, fetchDissents]);

  // Refresh on consensus events
  const latestConsensusEvent = useMemo(() => {
    const relevant = events.filter(
      (e) => e.type === 'consensus' || e.type === 'verdict' || e.type === 'grounded_verdict',
    );
    return relevant[relevant.length - 1];
  }, [events]);

  useEffect(() => {
    if (latestConsensusEvent && expanded) {
      fetchSettled();
      fetchStats();
      if (activeTab === 'dissents') {
        fetchDissents();
      }
    }
  }, [latestConsensusEvent, expanded, activeTab, fetchSettled, fetchStats, fetchDissents]);

  const formatTimestamp = (ts: string) => {
    if (!ts) return 'Unknown';
    const date = new Date(ts);
    return date.toLocaleDateString();
  };

  const getConfidenceColor = (conf: number) => {
    if (conf >= 0.9) return 'text-[var(--accent)]';
    if (conf >= 0.8) return 'text-[var(--acid-cyan)]';
    if (conf >= 0.7) return 'text-warning';
    return 'text-text-muted';
  };

  return (
    <div className="border border-[var(--accent)]/30 bg-surface/50">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-surface/80 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-[var(--accent)] font-theme-data text-sm">[KNOWLEDGE BASE]</span>
          <span className="text-text-muted text-xs">Settled consensus & history</span>
        </div>
        <span className="text-[var(--accent)]">{expanded ? '[-]' : '[+]'}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3">
          {/* Stats Banner */}
          {stats && (
            <div className="flex gap-4 text-xs text-text-muted border-b border-[var(--accent)]/20 pb-2">
              <span>{stats.total_topics || 0} topics</span>
              <span>{stats.high_confidence_count || 0} high-confidence</span>
              <span>Avg: {((stats.avg_confidence || 0) * 100).toFixed(0)}%</span>
            </div>
          )}

          {/* Tabs */}
          <div className="flex flex-wrap gap-1 border-b border-[var(--accent)]/20 pb-2">
            {(['settled', 'dissents', 'search', 'stats'] as TabType[]).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-2 py-1 text-xs font-theme-data transition-colors whitespace-nowrap ${
                  activeTab === tab
                    ? 'bg-[var(--accent)] text-bg'
                    : 'text-text-muted hover:text-[var(--accent)]'
                }`}
              >
                {tab.toUpperCase()}
              </button>
            ))}
          </div>

          {/* Content */}
          {loading ? (
            <div className="text-text-muted text-xs text-center py-4 animate-pulse">Loading...</div>
          ) : error ? (
            <div className="text-warning text-xs text-center py-4">{error}</div>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {activeTab === 'settled' &&
                (settledTopics.length === 0 ? (
                  <div className="text-text-muted text-xs text-center py-4">
                    No high-confidence topics yet
                  </div>
                ) : (
                  settledTopics.map((topic, idx) => (
                    <div
                      key={idx}
                      className="border border-[var(--accent)]/30 bg-surface p-2 text-xs"
                    >
                      <div className="flex justify-between items-start">
                        <span className="font-theme-data text-[var(--acid-cyan)] truncate max-w-[70%]">
                          {topic.topic}
                        </span>
                        <span className={getConfidenceColor(topic.confidence)}>
                          {(topic.confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                      <div className="text-text-muted mt-1 line-clamp-2">{topic.conclusion}</div>
                      <div className="text-text-muted/50 mt-1">
                        {formatTimestamp(topic.timestamp)}
                      </div>
                    </div>
                  ))
                ))}

              {activeTab === 'dissents' &&
                (dissents.length === 0 ? (
                  <div className="text-text-muted text-xs text-center py-4">
                    No dissenting views recorded yet
                  </div>
                ) : (
                  dissents.map((dissent, idx) => (
                    <div
                      key={idx}
                      className="border border-orange-500/30 bg-orange-900/10 p-2 text-xs"
                    >
                      <div className="font-theme-data text-orange-400 truncate mb-1">
                        {dissent.topic}
                      </div>
                      <div className="grid grid-cols-2 gap-2 mt-2">
                        <div>
                          <span className="text-text-muted">Majority: </span>
                          <span className="text-[var(--accent)]">{dissent.majority_view}</span>
                        </div>
                        <div>
                          <span className="text-text-muted">Dissent: </span>
                          <span className="text-orange-400">{dissent.dissenting_view}</span>
                        </div>
                      </div>
                      <div className="flex justify-between items-center mt-2 text-text-muted/70">
                        <span>By: {dissent.dissenting_agent}</span>
                        <span>{(dissent.confidence * 100).toFixed(0)}% confident</span>
                      </div>
                      {dissent.reasoning && (
                        <div className="mt-1 text-text-muted/60 italic">
                          &quot;{dissent.reasoning}&quot;
                        </div>
                      )}
                    </div>
                  ))
                ))}

              {activeTab === 'search' && (
                <div className="space-y-2">
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && searchSimilar()}
                      placeholder="Search for similar debates..."
                      className="flex-1 bg-bg border border-[var(--accent)]/30 px-2 py-1 text-xs font-theme-data text-[var(--accent)] placeholder:text-text-muted/50"
                    />
                    <button
                      onClick={searchSimilar}
                      disabled={!searchQuery.trim()}
                      className="px-2 py-1 text-xs bg-[var(--accent)]/20 text-[var(--accent)] hover:bg-[var(--accent)]/30 disabled:opacity-50"
                    >
                      SEARCH
                    </button>
                  </div>

                  {searchResults.length > 0 && (
                    <div className="space-y-2">
                      {searchResults.map((result, idx) => (
                        <div
                          key={idx}
                          className="border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 p-2 text-xs"
                        >
                          <div className="flex justify-between items-start">
                            <span className="font-theme-data text-[var(--acid-cyan)] truncate max-w-[60%]">
                              {result.topic}
                            </span>
                            <span className="text-text-muted">
                              {(result.similarity * 100).toFixed(0)}% match
                            </span>
                          </div>
                          <div className="text-text-muted mt-1 line-clamp-2">
                            {result.conclusion}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {activeTab === 'stats' && stats && (
                <div className="space-y-2 text-xs">
                  <div className="grid grid-cols-2 gap-2">
                    <div className="border border-[var(--accent)]/30 p-2">
                      <div className="text-text-muted">Total Topics</div>
                      <div className="text-[var(--accent)] text-lg font-theme-data">
                        {stats.total_topics || 0}
                      </div>
                    </div>
                    <div className="border border-[var(--accent)]/30 p-2">
                      <div className="text-text-muted">High Confidence</div>
                      <div className="text-[var(--acid-cyan)] text-lg font-theme-data">
                        {stats.high_confidence_count || 0}
                      </div>
                    </div>
                  </div>

                  {stats.domains && stats.domains.length > 0 && (
                    <div className="border border-[var(--accent)]/30 p-2">
                      <div className="text-text-muted mb-1">Domains</div>
                      <div className="flex flex-wrap gap-1">
                        {stats.domains.map((domain) => (
                          <span
                            key={domain}
                            className="px-1 py-0.5 bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/30"
                          >
                            {domain}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
