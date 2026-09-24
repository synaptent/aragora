/**
 * Types and constants for Gauntlet Dashboard
 */

export interface GauntletResult {
  gauntlet_id: string;
  input_summary: string;
  input_hash: string;
  verdict: string;
  confidence: number;
  robustness_score: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  total_findings: number;
  created_at: string;
  duration_seconds?: number;
}

export interface HeatmapCell {
  category: string;
  severity: string;
  count: number;
}

export interface HeatmapData {
  cells: HeatmapCell[];
  categories: string[];
  severities: string[];
  total_findings: number;
}

export interface GauntletDashboardProps {
  apiBase?: string;
  authToken?: string;
  onResultSelect?: (result: GauntletResult) => void;
}

export interface VerdictConfig {
  bg: string;
  border: string;
  text: string;
  icon: string;
}

export const VERDICT_CONFIG: Record<string, VerdictConfig> = {
  PASS: {
    bg: 'bg-acid-green/20',
    border: 'border-acid-green',
    text: 'text-acid-green',
    icon: '\u2713',
  },
  APPROVED: {
    bg: 'bg-acid-green/20',
    border: 'border-acid-green',
    text: 'text-acid-green',
    icon: '\u2713',
  },
  CONDITIONAL: {
    bg: 'bg-acid-yellow/20',
    border: 'border-acid-yellow',
    text: 'text-acid-yellow',
    icon: '\u26A0',
  },
  APPROVED_WITH_CONDITIONS: {
    bg: 'bg-acid-yellow/20',
    border: 'border-acid-yellow',
    text: 'text-acid-yellow',
    icon: '\u26A0',
  },
  NEEDS_REVIEW: {
    bg: 'bg-warning/20',
    border: 'border-warning',
    text: 'text-warning',
    icon: '\u2691',
  },
  FAIL: { bg: 'bg-acid-red/20', border: 'border-acid-red', text: 'text-acid-red', icon: '\u2717' },
  REJECTED: {
    bg: 'bg-acid-red/20',
    border: 'border-acid-red',
    text: 'text-acid-red',
    icon: '\u2717',
  },
  UNKNOWN: {
    bg: 'bg-text-muted/20',
    border: 'border-text-muted',
    text: 'text-text-muted',
    icon: '?',
  },
};

export const SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-acid-red',
  high: 'bg-warning',
  medium: 'bg-acid-yellow',
  low: 'bg-acid-cyan',
};
