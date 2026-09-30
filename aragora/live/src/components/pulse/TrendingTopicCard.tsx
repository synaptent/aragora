'use client';

import { useCallback } from 'react';
import { DebateThisButton } from '../DebateThisButton';

export interface TrendingTopic {
  topic: string;
  source: string;
  score: number;
  volume?: number;
  debate_count?: number;
  last_active?: string;
  category?: string;
  url?: string;
}

export interface TrendingTopicCardProps {
  topic: TrendingTopic;
  isSelected?: boolean;
  onClick?: () => void;
  onStartDebate?: () => void;
}

const SOURCE_ICONS: Record<string, string> = {
  hackernews: '🔶',
  reddit: '🤖',
  twitter: '🐦',
  github: '🐙',
  arxiv: '📄',
  debate: '💬',
  default: '📡',
};

const SOURCE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  hackernews: { bg: 'bg-orange-500/10', text: 'text-orange-400', border: 'border-orange-500/30' },
  reddit: { bg: 'bg-orange-600/10', text: 'text-orange-300', border: 'border-orange-600/30' },
  twitter: { bg: 'bg-blue-500/10', text: 'text-blue-400', border: 'border-blue-500/30' },
  github: { bg: 'bg-purple-500/10', text: 'text-purple-400', border: 'border-purple-500/30' },
  arxiv: { bg: 'bg-red-500/10', text: 'text-red-400', border: 'border-red-500/30' },
  debate: {
    bg: 'bg-[var(--accent)]/10',
    text: 'text-[var(--accent)]',
    border: 'border-[var(--accent)]/30',
  },
  default: { bg: 'bg-gray-500/10', text: 'text-gray-400', border: 'border-gray-500/30' },
};

const CATEGORY_COLORS: Record<string, string> = {
  tech: 'bg-blue-900/30 text-blue-400 border-blue-500/20',
  ai: 'bg-purple-900/30 text-purple-400 border-purple-500/20',
  science: 'bg-green-900/30 text-green-400 border-green-500/20',
  programming: 'bg-cyan-900/30 text-cyan-400 border-cyan-500/20',
  business: 'bg-yellow-900/30 text-yellow-400 border-yellow-500/20',
  health: 'bg-red-900/30 text-red-400 border-red-500/20',
  default: 'bg-gray-900/30 text-gray-400 border-gray-500/20',
};

export function TrendingTopicCard({
  topic,
  isSelected = false,
  onClick,
  onStartDebate: _onStartDebate,
}: TrendingTopicCardProps) {
  const sourceIcon = SOURCE_ICONS[topic.source.toLowerCase()] || SOURCE_ICONS.default;
  const sourceColors = SOURCE_COLORS[topic.source.toLowerCase()] || SOURCE_COLORS.default;
  const categoryClass = topic.category
    ? CATEGORY_COLORS[topic.category.toLowerCase()] || CATEGORY_COLORS.default
    : null;

  const getScoreColor = useCallback((score: number): string => {
    if (score >= 0.8) return 'text-yellow-400';
    if (score >= 0.6) return 'text-green-400';
    if (score >= 0.4) return 'text-blue-400';
    return 'text-text-muted';
  }, []);

  const getScoreBgColor = useCallback((score: number): string => {
    if (score >= 0.8) return 'bg-yellow-400/20';
    if (score >= 0.6) return 'bg-green-400/20';
    if (score >= 0.4) return 'bg-blue-400/20';
    return 'bg-gray-500/20';
  }, []);

  const formatTimeAgo = (timestamp: string): string => {
    const now = new Date();
    const then = new Date(timestamp);
    const diffMs = now.getTime() - then.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return then.toLocaleDateString();
  };

  const formatVolume = (volume: number): string => {
    if (volume >= 1000000) return `${(volume / 1000000).toFixed(1)}M`;
    if (volume >= 1000) return `${(volume / 1000).toFixed(1)}K`;
    return volume.toString();
  };

  return (
    <div
      onClick={onClick}
      className={`
        group relative p-4 bg-surface border rounded-lg cursor-pointer
        transition-all duration-200 hover:border-[var(--accent)]/50 hover:shadow-lg hover:shadow-acid-green/5
        ${isSelected ? 'border-[var(--accent)] ring-1 ring-acid-green/30' : 'border-border'}
      `}
    >
      {/* Score indicator bar */}
      <div
        className={`absolute top-0 left-0 h-1 rounded-tl-lg transition-all ${getScoreBgColor(topic.score)}`}
        style={{ width: `${Math.round(topic.score * 100)}%` }}
      />

      {/* Header with source and score */}
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-lg" title={topic.source}>
            {sourceIcon}
          </span>
          <span
            className={`px-2 py-0.5 text-xs font-theme-data rounded border ${sourceColors.bg} ${sourceColors.text} ${sourceColors.border}`}
          >
            {topic.source.toUpperCase()}
          </span>
        </div>
        <div
          className={`px-2 py-0.5 text-sm font-theme-data font-bold rounded ${getScoreBgColor(topic.score)} ${getScoreColor(topic.score)}`}
        >
          {Math.round(topic.score * 100)}%
        </div>
      </div>

      {/* Topic title */}
      <h3 className="text-sm font-theme-data text-text mb-2 line-clamp-2 group-hover:text-[var(--accent)] transition-colors">
        {topic.topic}
      </h3>

      {/* Metadata row */}
      <div className="flex items-center gap-3 text-xs text-text-muted mb-3">
        {topic.volume !== undefined && (
          <span title="Engagement volume">
            <span className="text-[var(--acid-cyan)]">{formatVolume(topic.volume)}</span> engagement
          </span>
        )}
        {topic.debate_count !== undefined && topic.debate_count > 0 && (
          <span>
            <span className="text-[var(--accent)]">{topic.debate_count}</span> debates
          </span>
        )}
        {topic.last_active && (
          <span className="text-text-muted/70">{formatTimeAgo(topic.last_active)}</span>
        )}
      </div>

      {/* Category tag and action button */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {categoryClass && (
            <span className={`px-2 py-0.5 text-xs font-theme-data rounded border ${categoryClass}`}>
              {topic.category}
            </span>
          )}
        </div>

        <div className="opacity-0 group-hover:opacity-100 transition-all duration-200">
          <DebateThisButton question={topic.topic} source="pulse" variant="button" />
        </div>
      </div>

      {/* Hover effect glow */}
      <div className="absolute inset-0 -z-10 opacity-0 group-hover:opacity-100 transition-opacity duration-300 rounded-lg bg-gradient-to-br from-acid-green/5 to-transparent" />
    </div>
  );
}

export default TrendingTopicCard;
