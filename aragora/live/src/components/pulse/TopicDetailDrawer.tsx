'use client';

import { useState, useCallback } from 'react';
import type { TrendingTopic } from './TrendingTopicCard';
import { DebateThisButton } from '../DebateThisButton';
import { logger } from '@/utils/logger';

export interface TopicDetailDrawerProps {
  topic: TrendingTopic | null;
  isOpen: boolean;
  onClose: () => void;
  onStartDebate: (topic: TrendingTopic, config: DebateConfig) => void;
  apiBase: string;
}

export interface DebateConfig {
  rounds: number;
  agentCount: number;
  focusAreas: string[];
}

const SOURCE_LINKS: Record<string, (topic: string) => string> = {
  hackernews: (topic) => `https://hn.algolia.com/?q=${encodeURIComponent(topic)}`,
  reddit: (topic) => `https://www.reddit.com/search/?q=${encodeURIComponent(topic)}`,
  twitter: (topic) => `https://twitter.com/search?q=${encodeURIComponent(topic)}`,
  github: (topic) => `https://github.com/search?q=${encodeURIComponent(topic)}`,
  arxiv: (topic) => `https://arxiv.org/search/?query=${encodeURIComponent(topic)}`,
};

const SOURCE_ICONS: Record<string, string> = {
  hackernews: '🔶',
  reddit: '🤖',
  twitter: '🐦',
  github: '🐙',
  arxiv: '📄',
};

export function TopicDetailDrawer({
  topic,
  isOpen,
  onClose,
  onStartDebate,
  apiBase,
}: TopicDetailDrawerProps) {
  const [debateConfig, setDebateConfig] = useState<DebateConfig>({
    rounds: 3,
    agentCount: 4,
    focusAreas: [],
  });
  const [customFocus, setCustomFocus] = useState('');
  const [isStarting, setIsStarting] = useState(false);

  const handleStartDebate = useCallback(async () => {
    if (!topic) return;

    setIsStarting(true);
    try {
      // Call the debate API
      const response = await fetch(`${apiBase}/api/pulse/debate-topic`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: topic.topic,
          source: topic.source,
          category: topic.category,
          config: debateConfig,
        }),
      });

      if (response.ok) {
        onStartDebate(topic, debateConfig);
        onClose();
      }
    } catch (err) {
      logger.error('Failed to start debate:', err);
    } finally {
      setIsStarting(false);
    }
  }, [topic, debateConfig, apiBase, onStartDebate, onClose]);

  const addFocusArea = useCallback(() => {
    if (customFocus.trim() && !debateConfig.focusAreas.includes(customFocus.trim())) {
      setDebateConfig((prev) => ({
        ...prev,
        focusAreas: [...prev.focusAreas, customFocus.trim()],
      }));
      setCustomFocus('');
    }
  }, [customFocus, debateConfig.focusAreas]);

  const removeFocusArea = useCallback((area: string) => {
    setDebateConfig((prev) => ({ ...prev, focusAreas: prev.focusAreas.filter((a) => a !== area) }));
  }, []);

  const getScoreColor = (score: number): string => {
    if (score >= 0.8) return 'text-yellow-400';
    if (score >= 0.6) return 'text-green-400';
    if (score >= 0.4) return 'text-blue-400';
    return 'text-text-muted';
  };

  const formatVolume = (volume: number): string => {
    if (volume >= 1000000) return `${(volume / 1000000).toFixed(1)}M`;
    if (volume >= 1000) return `${(volume / 1000).toFixed(1)}K`;
    return volume.toString();
  };

  if (!isOpen || !topic) return null;

  const sourceLink = SOURCE_LINKS[topic.source.toLowerCase()]?.(topic.topic);
  const sourceIcon = SOURCE_ICONS[topic.source.toLowerCase()] || '📡';

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-bg/80 backdrop-blur-sm z-40" onClick={onClose} />

      {/* Drawer */}
      <div className="fixed right-0 top-0 h-full w-full max-w-lg bg-surface border-l border-[var(--accent)]/30 z-50 flex flex-col shadow-2xl">
        {/* Header */}
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">{sourceIcon}</span>
            <span className="text-xs font-theme-data text-text-muted uppercase">
              {topic.source}
            </span>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center text-text-muted hover:text-[var(--accent)] transition-colors"
          >
            <span className="text-lg">×</span>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          {/* Topic title */}
          <div>
            <h2 className="text-lg font-theme-data text-[var(--accent)] leading-tight">
              {topic.topic}
            </h2>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-bg p-3 rounded border border-border">
              <div className="text-xs text-text-muted mb-1">SCORE</div>
              <div className={`text-2xl font-theme-data font-bold ${getScoreColor(topic.score)}`}>
                {Math.round(topic.score * 100)}%
              </div>
            </div>
            {topic.volume !== undefined && (
              <div className="bg-bg p-3 rounded border border-border">
                <div className="text-xs text-text-muted mb-1">ENGAGEMENT</div>
                <div className="text-2xl font-theme-data font-bold text-[var(--acid-cyan)]">
                  {formatVolume(topic.volume)}
                </div>
              </div>
            )}
            {topic.debate_count !== undefined && (
              <div className="bg-bg p-3 rounded border border-border">
                <div className="text-xs text-text-muted mb-1">DEBATES</div>
                <div className="text-2xl font-theme-data font-bold text-text">
                  {topic.debate_count}
                </div>
              </div>
            )}
            {topic.category && (
              <div className="bg-bg p-3 rounded border border-border">
                <div className="text-xs text-text-muted mb-1">CATEGORY</div>
                <div className="text-lg font-theme-data text-text capitalize">{topic.category}</div>
              </div>
            )}
          </div>

          {/* Source link */}
          {sourceLink && (
            <a
              href={sourceLink}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 p-3 bg-bg border border-border rounded hover:border-[var(--accent)]/50 transition-colors group"
            >
              <span className="text-lg">{sourceIcon}</span>
              <span className="flex-1 text-sm font-theme-data text-text-muted group-hover:text-text">
                View on {topic.source}
              </span>
              <span className="text-[var(--accent)]">→</span>
            </a>
          )}

          {/* Debate Configuration */}
          <div className="border-t border-border pt-4">
            <h3 className="text-xs font-theme-data text-[var(--accent)] uppercase mb-4">
              DEBATE CONFIGURATION
            </h3>

            {/* Rounds */}
            <div className="mb-4">
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs font-theme-data text-text-muted">ROUNDS</label>
                <span className="text-xs font-theme-data text-[var(--accent)]">
                  {debateConfig.rounds}
                </span>
              </div>
              <input
                type="range"
                min={1}
                max={10}
                value={debateConfig.rounds}
                onChange={(e) =>
                  setDebateConfig((prev) => ({ ...prev, rounds: parseInt(e.target.value) }))
                }
                className="w-full h-1 bg-border rounded appearance-none cursor-pointer accent-acid-green"
              />
              <div className="flex justify-between text-xs text-text-muted/50 mt-1">
                <span>Quick (1)</span>
                <span>Standard (5)</span>
                <span>Deep (10)</span>
              </div>
            </div>

            {/* Agent Count */}
            <div className="mb-4">
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs font-theme-data text-text-muted">AGENTS</label>
                <span className="text-xs font-theme-data text-[var(--accent)]">
                  {debateConfig.agentCount}
                </span>
              </div>
              <input
                type="range"
                min={2}
                max={8}
                value={debateConfig.agentCount}
                onChange={(e) =>
                  setDebateConfig((prev) => ({ ...prev, agentCount: parseInt(e.target.value) }))
                }
                className="w-full h-1 bg-border rounded appearance-none cursor-pointer accent-acid-green"
              />
              <div className="flex justify-between text-xs text-text-muted/50 mt-1">
                <span>2 agents</span>
                <span>5 agents</span>
                <span>8 agents</span>
              </div>
            </div>

            {/* Focus Areas */}
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-2">
                FOCUS AREAS (optional)
              </label>
              <div className="flex gap-2 mb-2">
                <input
                  type="text"
                  value={customFocus}
                  onChange={(e) => setCustomFocus(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && addFocusArea()}
                  placeholder="Add focus area..."
                  className="flex-1 px-3 py-2 bg-bg border border-border rounded text-sm font-theme-data text-text placeholder:text-text-muted/50 focus:border-[var(--accent)] focus:outline-none"
                />
                <button
                  onClick={addFocusArea}
                  className="px-3 py-2 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] text-sm font-theme-data rounded hover:bg-[var(--accent)]/30"
                >
                  +
                </button>
              </div>
              {debateConfig.focusAreas.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {debateConfig.focusAreas.map((area) => (
                    <span
                      key={area}
                      className="px-2 py-1 bg-[var(--acid-cyan)]/20 border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] text-xs font-theme-data rounded flex items-center gap-1"
                    >
                      {area}
                      <button
                        onClick={() => removeFocusArea(area)}
                        className="text-[var(--acid-cyan)]/70 hover:text-[var(--acid-cyan)]"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer with action buttons */}
        <div className="p-4 border-t border-border space-y-2">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-theme-data text-text-muted">Quick launch:</span>
            <DebateThisButton question={topic.topic} source="pulse" variant="button" />
          </div>
          <button
            onClick={handleStartDebate}
            disabled={isStarting}
            className="w-full py-3 bg-[var(--accent)] text-bg font-theme-data font-bold rounded hover:bg-[var(--accent)]/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isStarting ? 'Starting Debate...' : 'START WITH CONFIG'}
          </button>
          <button
            onClick={onClose}
            className="w-full py-2 border border-border text-text-muted font-theme-data text-sm rounded hover:border-text-muted transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    </>
  );
}

export default TopicDetailDrawer;
