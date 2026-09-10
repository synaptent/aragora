'use client';

import { useState, useEffect, useCallback } from 'react';
import { QualityMetrics, type QualityScore } from './QualityMetrics';
import { StalenessIndicator, type StalenessBucket } from './StalenessIndicator';
import { CoverageHeatmap, type TopicCoverage } from './CoverageHeatmap';

type QualitySubTab = 'overview' | 'freshness' | 'coverage';

export interface QualityData {
  overallScore: number;
  categoryScores: QualityScore[];
  stalenessBuckets: StalenessBucket[];
  totalNodes: number;
  avgAgeDays: number;
  recentUpdates: number;
  topicCoverage: TopicCoverage[];
}

export interface QualityTabProps {
  /** API base URL */
  apiUrl?: string;
  /** Workspace ID */
  workspaceId?: string;
  /** Initial data (if available) */
  initialData?: Partial<QualityData>;
  /** Loading state from parent */
  loading?: boolean;
  /** Callback when user wants to drill into a category */
  onDrillDown?: (type: 'category' | 'bucket' | 'topic', id: string) => void;
}

// Demo data for when API is not available
const DEMO_QUALITY_DATA: QualityData = {
  overallScore: 72,
  categoryScores: [
    { category: 'accuracy', score: 85, maxScore: 100, issues: ['2 nodes with conflicting claims'] },
    { category: 'freshness', score: 68, maxScore: 100, issues: ['15 nodes older than 30 days'] },
    { category: 'coverage', score: 75, maxScore: 100, issues: ['3 topics with gaps'] },
    { category: 'consistency', score: 82, maxScore: 100, issues: [] },
    { category: 'completeness', score: 60, maxScore: 100, issues: ['Missing metadata on 8 nodes'] },
    {
      category: 'provenance',
      score: 62,
      maxScore: 100,
      issues: ['12 nodes without source attribution'],
    },
  ],
  stalenessBuckets: [
    { label: '< 1 week', count: 450, maxDays: 7, status: 'fresh' },
    { label: '1-2 weeks', count: 280, maxDays: 14, status: 'fresh' },
    { label: '2-4 weeks', count: 150, maxDays: 28, status: 'aging' },
    { label: '1-2 months', count: 85, maxDays: 60, status: 'stale' },
    { label: '2-3 months', count: 45, maxDays: 90, status: 'stale' },
    { label: '> 3 months', count: 20, maxDays: 365, status: 'critical' },
  ],
  totalNodes: 1030,
  avgAgeDays: 18,
  recentUpdates: 42,
  topicCoverage: [
    {
      topic: 'architecture',
      name: 'Architecture',
      nodeCount: 125,
      coverage: 85,
      quality: 90,
      isGap: false,
    },
    { topic: 'api', name: 'API Design', nodeCount: 98, coverage: 78, quality: 82, isGap: false },
    { topic: 'security', name: 'Security', nodeCount: 76, coverage: 70, quality: 88, isGap: false },
    { topic: 'testing', name: 'Testing', nodeCount: 54, coverage: 45, quality: 75, isGap: false },
    {
      topic: 'deployment',
      name: 'Deployment',
      nodeCount: 42,
      coverage: 38,
      quality: 70,
      isGap: false,
    },
    {
      topic: 'monitoring',
      name: 'Monitoring',
      nodeCount: 28,
      coverage: 25,
      quality: 65,
      isGap: true,
    },
    {
      topic: 'compliance',
      name: 'Compliance',
      nodeCount: 15,
      coverage: 18,
      quality: 60,
      isGap: true,
    },
    {
      topic: 'performance',
      name: 'Performance',
      nodeCount: 68,
      coverage: 62,
      quality: 78,
      isGap: false,
    },
    {
      topic: 'debugging',
      name: 'Debugging',
      nodeCount: 32,
      coverage: 30,
      quality: 72,
      isGap: false,
    },
    {
      topic: 'onboarding',
      name: 'Onboarding',
      nodeCount: 8,
      coverage: 12,
      quality: 55,
      isGap: true,
    },
    {
      topic: 'integrations',
      name: 'Integrations',
      nodeCount: 45,
      coverage: 52,
      quality: 80,
      isGap: false,
    },
    {
      topic: 'data-models',
      name: 'Data Models',
      nodeCount: 89,
      coverage: 75,
      quality: 85,
      isGap: false,
    },
  ],
};

/**
 * Quality tab for the Knowledge Explorer showing metrics, freshness, and coverage.
 */
export function QualityTab({
  apiUrl = '/api',
  workspaceId,
  initialData,
  loading: parentLoading = false,
  onDrillDown,
}: QualityTabProps) {
  const [activeSubTab, setActiveSubTab] = useState<QualitySubTab>('overview');
  const [data, setData] = useState<QualityData | null>((initialData as QualityData) || null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch quality data
  const fetchQualityData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams();
      if (workspaceId) params.append('workspace_id', workspaceId);

      const response = await fetch(`${apiUrl}/v1/knowledge/quality?${params}`);

      if (!response.ok) {
        // Use demo data if API not available
        setData(DEMO_QUALITY_DATA);
        return;
      }

      const result = await response.json();
      setData(result);
    } catch {
      // Use demo data on error
      setData(DEMO_QUALITY_DATA);
    } finally {
      setLoading(false);
    }
  }, [apiUrl, workspaceId]);

  // Load data on mount
  useEffect(() => {
    if (!data) {
      fetchQualityData();
    }
  }, [data, fetchQualityData]);

  const isLoading = loading || parentLoading;
  const displayData = data || DEMO_QUALITY_DATA;

  return (
    <div className="space-y-4">
      {/* Sub-tab navigation */}
      <div className="flex items-center gap-2 border-b border-border pb-2">
        <button
          onClick={() => setActiveSubTab('overview')}
          className={`px-4 py-2 text-sm rounded-t transition-colors ${
            activeSubTab === 'overview'
              ? 'bg-surface text-[var(--accent)] border-b-2 border-[var(--accent)]'
              : 'text-text-muted hover:text-white'
          }`}
        >
          Overview
        </button>
        <button
          onClick={() => setActiveSubTab('freshness')}
          className={`px-4 py-2 text-sm rounded-t transition-colors ${
            activeSubTab === 'freshness'
              ? 'bg-surface text-[var(--accent)] border-b-2 border-[var(--accent)]'
              : 'text-text-muted hover:text-white'
          }`}
        >
          Freshness
        </button>
        <button
          onClick={() => setActiveSubTab('coverage')}
          className={`px-4 py-2 text-sm rounded-t transition-colors ${
            activeSubTab === 'coverage'
              ? 'bg-surface text-[var(--accent)] border-b-2 border-[var(--accent)]'
              : 'text-text-muted hover:text-white'
          }`}
        >
          Coverage
        </button>

        <div className="flex-1" />

        <button
          onClick={fetchQualityData}
          disabled={isLoading}
          className="text-xs text-text-muted hover:text-[var(--accent)] transition-colors
                     disabled:opacity-50"
        >
          {isLoading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {/* Error display */}
      {error && (
        <div className="p-3 bg-red-500/10 border border-red-500/20 rounded text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Content based on active sub-tab */}
      {activeSubTab === 'overview' && (
        <QualityMetrics
          overallScore={displayData.overallScore}
          categoryScores={displayData.categoryScores}
          loading={isLoading}
          onCategoryClick={(category) => onDrillDown?.('category', category)}
        />
      )}

      {activeSubTab === 'freshness' && (
        <StalenessIndicator
          buckets={displayData.stalenessBuckets}
          totalNodes={displayData.totalNodes}
          avgAgeDays={displayData.avgAgeDays}
          recentUpdates={displayData.recentUpdates}
          loading={isLoading}
          onBucketClick={(bucket) => onDrillDown?.('bucket', bucket.label)}
        />
      )}

      {activeSubTab === 'coverage' && (
        <CoverageHeatmap
          topics={displayData.topicCoverage}
          loading={isLoading}
          onTopicClick={(topic) => onDrillDown?.('topic', topic.topic)}
        />
      )}
    </div>
  );
}

export default QualityTab;
