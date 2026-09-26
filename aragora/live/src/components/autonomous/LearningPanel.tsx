'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '@/config';

interface Calibration {
  elo_rating: number;
  total_debates: number;
  win_rate: number;
  last_updated: string | null;
}

interface Pattern {
  id: string;
  pattern_type: string;
  description: string;
  confidence: number;
  evidence_count: number;
  first_seen: string;
  last_seen: string;
  agents_involved: string[];
  topics: string[];
}

interface LearningPanelProps {
  apiBase: string;
}

export function LearningPanel({ apiBase }: LearningPanelProps) {
  const [ratings, setRatings] = useState<Record<string, number>>({});
  const [calibrations, setCalibrations] = useState<Record<string, Calibration>>({});
  const [patterns, setPatterns] = useState<Pattern[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'ratings' | 'calibrations' | 'patterns'>('ratings');
  const [runningLearning, setRunningLearning] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [ratingsRes, calibrationsRes, patternsRes] = await Promise.all([
        apiFetch<{ ratings: Record<string, number> }>(`${apiBase}/autonomous/learning/ratings`),
        apiFetch<{ calibrations: Record<string, Calibration> }>(
          `${apiBase}/autonomous/learning/calibrations`,
        ),
        apiFetch<{ patterns: Pattern[] }>(`${apiBase}/autonomous/learning/patterns`),
      ]);
      if (ratingsRes.error) {
        throw new Error(ratingsRes.error);
      }
      if (calibrationsRes.error) {
        throw new Error(calibrationsRes.error);
      }
      if (patternsRes.error) {
        throw new Error(patternsRes.error);
      }
      setRatings(ratingsRes.data?.ratings ?? {});
      setCalibrations(calibrationsRes.data?.calibrations ?? {});
      setPatterns(patternsRes.data?.patterns ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch learning data');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleRunLearning = async () => {
    try {
      setRunningLearning(true);
      await apiFetch(`${apiBase}/autonomous/learning/run`, { method: 'POST' });
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to run learning cycle');
    } finally {
      setRunningLearning(false);
    }
  };

  const formatRating = (rating: number) => {
    return Math.round(rating);
  };

  const getRatingColor = (rating: number) => {
    if (rating >= 1800) return 'text-purple-400';
    if (rating >= 1600) return 'text-[var(--acid-cyan)]';
    if (rating >= 1400) return 'text-[var(--accent)]';
    if (rating >= 1200) return 'text-yellow-500';
    return 'text-white/50';
  };

  if (loading && Object.keys(ratings).length === 0) {
    return <div className="text-white/50 animate-pulse">Loading learning data...</div>;
  }

  if (error) {
    return (
      <div className="p-4 bg-red-500/10 border border-red-500/30 rounded text-red-400">
        {error}
        <button onClick={fetchData} className="ml-4 text-sm underline">
          Retry
        </button>
      </div>
    );
  }

  const renderRatings = () => {
    const sortedRatings = Object.entries(ratings).sort((a, b) => b[1] - a[1]);

    if (sortedRatings.length === 0) {
      return (
        <div className="text-center py-12 text-white/50">
          <div className="text-4xl mb-2">🏆</div>
          <div>No agent ratings yet</div>
          <div className="text-xs mt-1">Ratings are updated after debates</div>
        </div>
      );
    }

    return (
      <div className="space-y-2">
        {sortedRatings.map(([agent, rating], index) => (
          <div
            key={agent}
            className="flex items-center justify-between p-3 border border-white/10 bg-white/5 rounded-lg"
          >
            <div className="flex items-center gap-3">
              <span className="text-white/30 text-sm font-theme-data w-6">#{index + 1}</span>
              <span className="font-medium text-white">{agent}</span>
            </div>
            <span className={`text-lg font-bold ${getRatingColor(rating)}`}>
              {formatRating(rating)}
            </span>
          </div>
        ))}
      </div>
    );
  };

  const renderCalibrations = () => {
    const sortedCalibrations = Object.entries(calibrations).sort(
      (a, b) => b[1].elo_rating - a[1].elo_rating,
    );

    if (sortedCalibrations.length === 0) {
      return (
        <div className="text-center py-12 text-white/50">
          <div className="text-4xl mb-2">📊</div>
          <div>No calibration data yet</div>
        </div>
      );
    }

    return (
      <div className="space-y-2">
        {sortedCalibrations.map(([agent, cal]) => (
          <div key={agent} className="p-4 border border-white/10 bg-white/5 rounded-lg">
            <div className="flex items-center justify-between mb-2">
              <span className="font-medium text-white">{agent}</span>
              <span className={`text-lg font-bold ${getRatingColor(cal.elo_rating)}`}>
                {formatRating(cal.elo_rating)}
              </span>
            </div>
            <div className="grid grid-cols-3 gap-4 text-sm">
              <div>
                <div className="text-white/40 text-xs">Debates</div>
                <div className="text-white">{cal.total_debates}</div>
              </div>
              <div>
                <div className="text-white/40 text-xs">Win Rate</div>
                <div className={cal.win_rate >= 0.5 ? 'text-[var(--accent)]' : 'text-red-400'}>
                  {(cal.win_rate * 100).toFixed(1)}%
                </div>
              </div>
              <div>
                <div className="text-white/40 text-xs">Last Updated</div>
                <div className="text-white/50 text-xs">
                  {cal.last_updated ? new Date(cal.last_updated).toLocaleDateString() : '-'}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  };

  const renderPatterns = () => {
    if (patterns.length === 0) {
      return (
        <div className="text-center py-12 text-white/50">
          <div className="text-4xl mb-2">🔍</div>
          <div>No patterns discovered yet</div>
          <div className="text-xs mt-1">Patterns emerge from debate analysis</div>
        </div>
      );
    }

    return (
      <div className="space-y-2">
        {patterns.map((pattern) => (
          <div key={pattern.id} className="p-4 border border-white/10 bg-white/5 rounded-lg">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="px-2 py-0.5 rounded text-xs bg-purple-500/20 text-purple-400">
                    {pattern.pattern_type}
                  </span>
                  <span className="text-xs text-white/40">
                    {(pattern.confidence * 100).toFixed(0)}% confidence
                  </span>
                </div>
                <div className="text-sm text-white">{pattern.description}</div>
                <div className="flex flex-wrap gap-2 mt-2">
                  {pattern.agents_involved.map((agent) => (
                    <span
                      key={agent}
                      className="px-1.5 py-0.5 rounded text-xs bg-white/10 text-white/50"
                    >
                      {agent}
                    </span>
                  ))}
                  {pattern.topics.map((topic) => (
                    <span
                      key={topic}
                      className="px-1.5 py-0.5 rounded text-xs bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)]"
                    >
                      {topic}
                    </span>
                  ))}
                </div>
              </div>
              <div className="text-xs text-white/40 text-right">
                <div>{pattern.evidence_count} evidence</div>
                <div>{new Date(pattern.last_seen).toLocaleDateString()}</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div role="tablist" aria-label="Learning data views" className="flex gap-2">
          <button
            role="tab"
            aria-selected={activeTab === 'ratings'}
            aria-controls="ratings-panel"
            onClick={() => setActiveTab('ratings')}
            className={`px-3 py-1.5 text-sm rounded transition-colors ${
              activeTab === 'ratings' ? 'bg-white/10 text-white' : 'text-white/50 hover:text-white'
            }`}
          >
            Ratings ({Object.keys(ratings).length})
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'calibrations'}
            aria-controls="calibrations-panel"
            onClick={() => setActiveTab('calibrations')}
            className={`px-3 py-1.5 text-sm rounded transition-colors ${
              activeTab === 'calibrations'
                ? 'bg-white/10 text-white'
                : 'text-white/50 hover:text-white'
            }`}
          >
            Calibrations ({Object.keys(calibrations).length})
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'patterns'}
            aria-controls="patterns-panel"
            onClick={() => setActiveTab('patterns')}
            className={`px-3 py-1.5 text-sm rounded transition-colors ${
              activeTab === 'patterns' ? 'bg-white/10 text-white' : 'text-white/50 hover:text-white'
            }`}
          >
            Patterns ({patterns.length})
          </button>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleRunLearning}
            disabled={runningLearning}
            aria-label={runningLearning ? 'Learning cycle in progress' : 'Run learning cycle'}
            className="px-3 py-1.5 text-xs bg-purple-500/20 hover:bg-purple-500/30 text-purple-400 rounded transition-colors disabled:opacity-50"
          >
            {runningLearning ? 'Running...' : 'Run Learning Cycle'}
          </button>
          <button
            onClick={fetchData}
            disabled={loading}
            aria-label="Refresh learning data"
            className="text-xs text-white/50 hover:text-white"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Content */}
      {activeTab === 'ratings' && (
        <div role="tabpanel" id="ratings-panel" aria-labelledby="ratings-tab">
          {renderRatings()}
        </div>
      )}
      {activeTab === 'calibrations' && (
        <div role="tabpanel" id="calibrations-panel" aria-labelledby="calibrations-tab">
          {renderCalibrations()}
        </div>
      )}
      {activeTab === 'patterns' && (
        <div role="tabpanel" id="patterns-panel" aria-labelledby="patterns-tab">
          {renderPatterns()}
        </div>
      )}
    </div>
  );
}

export default LearningPanel;
