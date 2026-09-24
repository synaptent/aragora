'use client';

import useSWR from 'swr';
import { API_BASE_URL } from '@/config';

// --- Types ---

interface MetaPlannerGoal {
  id: string;
  description: string;
  track: string;
  confidence: number;
  signals: string[];
  reasoning: string;
  priority: number;
}

interface GoalsResponse {
  data: {
    goals: MetaPlannerGoal[];
    signals_used: string[];
    enrichment_context: Record<string, unknown>;
  };
}

interface BranchEntry {
  branch_name: string;
  worktree_path: string;
  status: 'active' | 'testing' | 'merged' | 'rejected';
  subtask: string;
  created_at: string;
}

interface TimelineResponse {
  data: {
    branches: BranchEntry[];
    merge_decisions: Array<{ branch: string; decision: string; reason: string }>;
    active_count: number;
  };
}

interface LearningInsight {
  cycle_id: string;
  insight_type: 'high_roi' | 'recurring_failure' | 'calibration';
  description: string;
  confidence: number;
  timestamp: string;
}

interface InsightsResponse {
  data: {
    insights: LearningInsight[];
    high_roi_patterns: Array<{ pattern: string; roi_score: number }>;
    recurring_failures: Array<{ description: string; occurrences: number }>;
  };
}

interface MetricComparison {
  metric_name: string;
  before: number;
  after: number;
  delta: number;
  is_regression: boolean;
}

interface ComparisonResponse {
  data: {
    comparisons: MetricComparison[];
    regressions: MetricComparison[];
    overall_health: 'improved' | 'stable' | 'degraded';
  };
}

// --- Hooks ---

const fetcher = (url: string) => fetch(url).then((r) => r.json());

export function useMetaPlannerGoals() {
  const { data, error, isLoading, mutate } = useSWR<GoalsResponse>(
    `${API_BASE_URL}/api/self-improve/meta-planner/goals`,
    fetcher,
    { refreshInterval: 10000 },
  );
  return {
    goals: data?.data?.goals ?? [],
    signals: data?.data?.signals_used ?? [],
    enrichment: data?.data?.enrichment_context ?? {},
    loading: isLoading,
    error,
    refresh: mutate,
  };
}

export function useExecutionTimeline() {
  const { data, error, isLoading, mutate } = useSWR<TimelineResponse>(
    `${API_BASE_URL}/api/self-improve/execution/timeline`,
    fetcher,
    { refreshInterval: 5000 },
  );
  return {
    branches: data?.data?.branches ?? [],
    mergeDecisions: data?.data?.merge_decisions ?? [],
    activeCount: data?.data?.active_count ?? 0,
    loading: isLoading,
    error,
    refresh: mutate,
  };
}

export function useLearningInsights() {
  const { data, error, isLoading, mutate } = useSWR<InsightsResponse>(
    `${API_BASE_URL}/api/self-improve/learning/insights`,
    fetcher,
    { refreshInterval: 15000 },
  );
  return {
    insights: data?.data?.insights ?? [],
    highRoiPatterns: data?.data?.high_roi_patterns ?? [],
    recurringFailures: data?.data?.recurring_failures ?? [],
    loading: isLoading,
    error,
    refresh: mutate,
  };
}

export function useMetricsComparison() {
  const { data, error, isLoading, mutate } = useSWR<ComparisonResponse>(
    `${API_BASE_URL}/api/self-improve/metrics/comparison`,
    fetcher,
    { refreshInterval: 15000 },
  );
  return {
    comparisons: data?.data?.comparisons ?? [],
    regressions: data?.data?.regressions ?? [],
    overallHealth: data?.data?.overall_health ?? 'stable',
    loading: isLoading,
    error,
    refresh: mutate,
  };
}
