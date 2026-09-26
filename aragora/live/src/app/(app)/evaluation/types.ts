/**
 * Evaluation Page Types and Helpers
 *
 * Shared types, interfaces, and helper functions for the Evaluation page.
 */

// =============================================================================
// Interfaces
// =============================================================================

export interface Dimension {
  id: string;
  name: string;
  description: string;
  rubric: { score_1: string; score_2: string; score_3: string; score_4: string; score_5: string };
}

export interface Profile {
  id: string;
  name: string;
  description: string;
  weights: Record<string, number>;
}

export interface EvaluationResult {
  overall_score: number;
  passed: boolean;
  dimension_scores: Record<string, number>;
  weighted_score: number;
  reasoning?: string;
  metadata?: Record<string, unknown>;
}

export interface CompareResult {
  winner: 'A' | 'B' | 'tie';
  confidence: number;
  reasoning: string;
  scores_a?: Record<string, number>;
  scores_b?: Record<string, number>;
}

// =============================================================================
// Helper Functions
// =============================================================================

export function getScoreColor(score: number): string {
  if (score >= 4) return 'text-acid-green';
  if (score >= 3) return 'text-acid-yellow';
  if (score >= 2) return 'text-warning';
  return 'text-crimson';
}
