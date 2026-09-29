'use client';

import { useMemo } from 'react';

export interface QualityScore {
  category: string;
  score: number;
  maxScore: number;
  issues: string[];
}

export interface QualityMetricsProps {
  /** Overall quality score (0-100) */
  overallScore: number;
  /** Category-specific scores */
  categoryScores: QualityScore[];
  /** Whether data is loading */
  loading?: boolean;
  /** Callback when a category is clicked */
  onCategoryClick?: (category: string) => void;
}

/**
 * Displays knowledge quality metrics and scores.
 */
export function QualityMetrics({
  overallScore,
  categoryScores,
  loading = false,
  onCategoryClick,
}: QualityMetricsProps) {
  const scoreColor = useMemo(() => {
    if (overallScore >= 80) return 'text-green-400';
    if (overallScore >= 60) return 'text-yellow-400';
    if (overallScore >= 40) return 'text-orange-400';
    return 'text-red-400';
  }, [overallScore]);

  const scoreBg = useMemo(() => {
    if (overallScore >= 80) return 'from-green-500/20 to-green-500/5';
    if (overallScore >= 60) return 'from-yellow-500/20 to-yellow-500/5';
    if (overallScore >= 40) return 'from-orange-500/20 to-orange-500/5';
    return 'from-red-500/20 to-red-500/5';
  }, [overallScore]);

  if (loading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-24 bg-surface-lighter rounded-lg" />
        <div className="grid grid-cols-2 gap-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-20 bg-surface-lighter rounded-lg" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Overall Score */}
      <div className={`p-4 rounded-lg bg-gradient-to-br ${scoreBg} border border-border`}>
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm text-text-muted mb-1">Overall Quality Score</div>
            <div className={`text-4xl font-theme-data font-bold ${scoreColor}`}>
              {overallScore}
              <span className="text-lg text-text-muted">/100</span>
            </div>
          </div>
          <div className="text-right">
            <QualityGauge score={overallScore} size={80} />
          </div>
        </div>
        <div className="mt-3 text-xs text-text-muted">
          {overallScore >= 80 && 'Excellent knowledge quality - well maintained and accurate'}
          {overallScore >= 60 &&
            overallScore < 80 &&
            'Good quality - minor improvements recommended'}
          {overallScore >= 40 && overallScore < 60 && 'Fair quality - several areas need attention'}
          {overallScore < 40 && 'Poor quality - immediate attention required'}
        </div>
      </div>

      {/* Category Scores */}
      <div className="grid grid-cols-2 gap-3">
        {categoryScores.map((category) => (
          <CategoryScoreCard
            key={category.category}
            category={category}
            onClick={() => onCategoryClick?.(category.category)}
          />
        ))}
      </div>
    </div>
  );
}

interface QualityGaugeProps {
  score: number;
  size?: number;
}

function QualityGauge({ score, size = 80 }: QualityGaugeProps) {
  const radius = (size - 10) / 2;
  const circumference = 2 * Math.PI * radius;
  const progress = (score / 100) * circumference;
  const offset = circumference - progress;

  const strokeColor = useMemo(() => {
    if (score >= 80) return '#4ade80';
    if (score >= 60) return '#facc15';
    if (score >= 40) return '#fb923c';
    return '#f87171';
  }, [score]);

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {/* Background circle */}
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="currentColor"
        strokeWidth="6"
        className="text-surface-lighter"
      />
      {/* Progress circle */}
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={strokeColor}
        strokeWidth="6"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        className="transition-all duration-500"
      />
    </svg>
  );
}

interface CategoryScoreCardProps {
  category: QualityScore;
  onClick?: () => void;
}

function CategoryScoreCard({ category, onClick }: CategoryScoreCardProps) {
  const percentage = Math.round((category.score / category.maxScore) * 100);

  const barColor = useMemo(() => {
    if (percentage >= 80) return 'bg-green-500';
    if (percentage >= 60) return 'bg-yellow-500';
    if (percentage >= 40) return 'bg-orange-500';
    return 'bg-red-500';
  }, [percentage]);

  const categoryIcon: Record<string, string> = {
    accuracy: '?',
    freshness: '?',
    coverage: '?',
    consistency: '?',
    completeness: '?',
    provenance: '?',
  };

  return (
    <button
      onClick={onClick}
      className="p-3 bg-surface rounded-lg border border-border hover:border-[var(--accent)]/30
                 transition-colors text-left w-full"
    >
      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">{categoryIcon[category.category.toLowerCase()] || '?'}</span>
        <span className="text-sm font-medium capitalize">{category.category}</span>
      </div>

      <div className="flex items-center gap-2 mb-1">
        <div className="flex-1 h-2 bg-surface-lighter rounded-full overflow-hidden">
          <div
            className={`h-full ${barColor} transition-all duration-300`}
            style={{ width: `${percentage}%` }}
          />
        </div>
        <span className="text-sm font-theme-data text-text-muted w-12 text-right">
          {percentage}%
        </span>
      </div>

      {category.issues.length > 0 && (
        <div className="text-xs text-text-muted mt-2">
          {category.issues.length} issue{category.issues.length !== 1 ? 's' : ''} found
        </div>
      )}
    </button>
  );
}

export default QualityMetrics;
