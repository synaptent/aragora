'use client';

import { useMemo, useState } from 'react';

export interface TopicCoverage {
  /** Topic identifier */
  topic: string;
  /** Display name */
  name: string;
  /** Number of nodes covering this topic */
  nodeCount: number;
  /** Coverage score (0-100) */
  coverage: number;
  /** Quality score (0-100) */
  quality: number;
  /** Whether this is a gap (low coverage) */
  isGap: boolean;
  /** Sub-topics if hierarchical */
  children?: TopicCoverage[];
}

export interface CoverageHeatmapProps {
  /** Topic coverage data */
  topics: TopicCoverage[];
  /** Loading state */
  loading?: boolean;
  /** Callback when topic is clicked */
  onTopicClick?: (topic: TopicCoverage) => void;
  /** Show hierarchical view */
  hierarchical?: boolean;
}

/**
 * Heatmap visualization showing topic coverage across the knowledge base.
 */
export function CoverageHeatmap({
  topics,
  loading = false,
  onTopicClick,
  hierarchical = false,
}: CoverageHeatmapProps) {
  const [viewMode, setViewMode] = useState<'heatmap' | 'list' | 'gaps'>('heatmap');

  const sortedTopics = useMemo(
    () => [...topics].sort((a, b) => b.nodeCount - a.nodeCount),
    [topics],
  );

  const gaps = useMemo(() => topics.filter((t) => t.isGap), [topics]);

  const maxNodes = useMemo(() => Math.max(...topics.map((t) => t.nodeCount), 1), [topics]);

  if (loading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="flex gap-2 mb-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-8 w-20 bg-surface-lighter rounded" />
          ))}
        </div>
        <div className="grid grid-cols-4 gap-2">
          {[...Array(12)].map((_, i) => (
            <div key={i} className="h-16 bg-surface-lighter rounded" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* View Mode Toggle */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setViewMode('heatmap')}
          className={`px-3 py-1.5 text-xs rounded transition-colors ${
            viewMode === 'heatmap'
              ? 'bg-[var(--accent)] text-black'
              : 'bg-surface hover:bg-surface-lighter'
          }`}
        >
          Heatmap
        </button>
        <button
          onClick={() => setViewMode('list')}
          className={`px-3 py-1.5 text-xs rounded transition-colors ${
            viewMode === 'list'
              ? 'bg-[var(--accent)] text-black'
              : 'bg-surface hover:bg-surface-lighter'
          }`}
        >
          List
        </button>
        <button
          onClick={() => setViewMode('gaps')}
          className={`px-3 py-1.5 text-xs rounded transition-colors ${
            viewMode === 'gaps'
              ? 'bg-[var(--accent)] text-black'
              : 'bg-surface hover:bg-surface-lighter'
          }`}
        >
          Gaps ({gaps.length})
        </button>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-4 gap-3">
        <div className="p-3 bg-surface rounded-lg border border-border text-center">
          <div className="text-2xl font-theme-data font-bold text-[var(--acid-cyan)]">
            {topics.length}
          </div>
          <div className="text-xs text-text-muted">Topics</div>
        </div>
        <div className="p-3 bg-surface rounded-lg border border-border text-center">
          <div className="text-2xl font-theme-data font-bold text-green-400">
            {topics.filter((t) => t.coverage >= 70).length}
          </div>
          <div className="text-xs text-text-muted">Well Covered</div>
        </div>
        <div className="p-3 bg-surface rounded-lg border border-border text-center">
          <div className="text-2xl font-theme-data font-bold text-yellow-400">
            {topics.filter((t) => t.coverage >= 30 && t.coverage < 70).length}
          </div>
          <div className="text-xs text-text-muted">Partial</div>
        </div>
        <div className="p-3 bg-surface rounded-lg border border-border text-center">
          <div className="text-2xl font-theme-data font-bold text-red-400">{gaps.length}</div>
          <div className="text-xs text-text-muted">Gaps</div>
        </div>
      </div>

      {/* Content based on view mode */}
      {viewMode === 'heatmap' && (
        <HeatmapView
          topics={sortedTopics}
          maxNodes={maxNodes}
          onTopicClick={onTopicClick}
          hierarchical={hierarchical}
        />
      )}

      {viewMode === 'list' && <ListView topics={sortedTopics} onTopicClick={onTopicClick} />}

      {viewMode === 'gaps' && <GapsView gaps={gaps} onTopicClick={onTopicClick} />}
    </div>
  );
}

interface HeatmapViewProps {
  topics: TopicCoverage[];
  maxNodes: number;
  onTopicClick?: (topic: TopicCoverage) => void;
  hierarchical: boolean;
}

function HeatmapView({ topics, maxNodes, onTopicClick, hierarchical }: HeatmapViewProps) {
  const getCoverageColor = (coverage: number) => {
    if (coverage >= 80) return 'bg-green-500';
    if (coverage >= 60) return 'bg-green-600';
    if (coverage >= 40) return 'bg-yellow-500';
    if (coverage >= 20) return 'bg-orange-500';
    return 'bg-red-500';
  };

  const getCoverageOpacity = (nodeCount: number) => {
    const ratio = nodeCount / maxNodes;
    return Math.max(0.3, ratio);
  };

  if (hierarchical) {
    return (
      <div className="space-y-2">
        {topics
          .filter((t) => t.children && t.children.length > 0)
          .map((parent) => (
            <div key={parent.topic} className="border border-border rounded-lg overflow-hidden">
              <button
                onClick={() => onTopicClick?.(parent)}
                className="w-full p-3 bg-surface hover:bg-surface-lighter transition-colors
                           flex items-center justify-between"
              >
                <span className="font-medium">{parent.name}</span>
                <span className="text-sm text-text-muted">{parent.nodeCount} nodes</span>
              </button>
              <div className="grid grid-cols-4 gap-1 p-2 bg-surface-lighter">
                {parent.children?.map((child) => (
                  <button
                    key={child.topic}
                    onClick={() => onTopicClick?.(child)}
                    className={`p-2 rounded text-xs ${getCoverageColor(child.coverage)}
                               hover:opacity-80 transition-opacity`}
                    style={{ opacity: getCoverageOpacity(child.nodeCount) }}
                    title={`${child.name}: ${child.coverage}% coverage, ${child.nodeCount} nodes`}
                  >
                    {child.name}
                  </button>
                ))}
              </div>
            </div>
          ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-4 gap-2">
      {topics.map((topic) => (
        <button
          key={topic.topic}
          onClick={() => onTopicClick?.(topic)}
          className={`p-3 rounded-lg ${getCoverageColor(topic.coverage)}
                     hover:opacity-80 transition-all text-left`}
          style={{ opacity: getCoverageOpacity(topic.nodeCount) }}
          title={`${topic.name}: ${topic.coverage}% coverage, ${topic.nodeCount} nodes`}
        >
          <div className="text-sm font-medium text-white truncate">{topic.name}</div>
          <div className="text-xs text-white/70 mt-1">
            {topic.nodeCount} nodes - {topic.coverage}%
          </div>
        </button>
      ))}
    </div>
  );
}

interface ListViewProps {
  topics: TopicCoverage[];
  onTopicClick?: (topic: TopicCoverage) => void;
}

function ListView({ topics, onTopicClick }: ListViewProps) {
  return (
    <div className="space-y-1">
      {topics.map((topic) => (
        <button
          key={topic.topic}
          onClick={() => onTopicClick?.(topic)}
          className="w-full p-3 bg-surface rounded-lg border border-border
                     hover:border-[var(--accent)]/30 transition-colors flex items-center gap-3"
        >
          <div className="flex-1 text-left">
            <div className="font-medium">{topic.name}</div>
            <div className="text-xs text-text-muted">{topic.nodeCount} nodes</div>
          </div>

          <div className="w-32">
            <div className="flex items-center gap-2 mb-1">
              <div className="flex-1 h-2 bg-surface-lighter rounded-full overflow-hidden">
                <div
                  className={`h-full transition-all ${
                    topic.coverage >= 70
                      ? 'bg-green-500'
                      : topic.coverage >= 40
                        ? 'bg-yellow-500'
                        : 'bg-red-500'
                  }`}
                  style={{ width: `${topic.coverage}%` }}
                />
              </div>
              <span className="text-xs font-theme-data w-8">{topic.coverage}%</span>
            </div>
          </div>

          <div className="w-20 text-right">
            <div
              className={`text-xs px-2 py-0.5 rounded ${
                topic.quality >= 70
                  ? 'bg-green-500/20 text-green-400'
                  : topic.quality >= 40
                    ? 'bg-yellow-500/20 text-yellow-400'
                    : 'bg-red-500/20 text-red-400'
              }`}
            >
              Q: {topic.quality}%
            </div>
          </div>
        </button>
      ))}
    </div>
  );
}

interface GapsViewProps {
  gaps: TopicCoverage[];
  onTopicClick?: (topic: TopicCoverage) => void;
}

function GapsView({ gaps, onTopicClick }: GapsViewProps) {
  if (gaps.length === 0) {
    return (
      <div className="p-8 text-center text-text-muted">
        <div className="text-4xl mb-2">?</div>
        <div>No coverage gaps detected!</div>
        <div className="text-sm">All topics have adequate coverage.</div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-sm text-red-400">
        {gaps.length} topic{gaps.length !== 1 ? 's' : ''} with insufficient coverage detected.
        Consider adding more knowledge in these areas.
      </div>

      {gaps.map((gap) => (
        <button
          key={gap.topic}
          onClick={() => onTopicClick?.(gap)}
          className="w-full p-4 bg-surface rounded-lg border border-red-500/30
                     hover:border-red-500/50 transition-colors text-left"
        >
          <div className="flex items-start justify-between">
            <div>
              <div className="font-medium text-red-400">{gap.name}</div>
              <div className="text-sm text-text-muted mt-1">
                Only {gap.nodeCount} node{gap.nodeCount !== 1 ? 's' : ''} covering this topic
              </div>
            </div>
            <div className="text-right">
              <div className="text-2xl font-theme-data text-red-400">{gap.coverage}%</div>
              <div className="text-xs text-text-muted">coverage</div>
            </div>
          </div>

          <div className="mt-3 flex items-center gap-2">
            <div className="flex-1 h-2 bg-surface-lighter rounded-full overflow-hidden">
              <div className="h-full bg-red-500" style={{ width: `${gap.coverage}%` }} />
            </div>
          </div>
        </button>
      ))}
    </div>
  );
}

export default CoverageHeatmap;
