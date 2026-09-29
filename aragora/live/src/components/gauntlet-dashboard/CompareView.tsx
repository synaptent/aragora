'use client';

import React, { useState, useEffect } from 'react';
import { VerdictBadge } from './VerdictBadge';
import type { GauntletResult } from './types';
import { logger } from '@/utils/logger';

interface CompareViewProps {
  result1: GauntletResult;
  result2: GauntletResult;
  apiBase: string;
  onClose: () => void;
}

export function CompareView({ result1, result2, apiBase, onClose }: CompareViewProps) {
  const [comparison, setComparison] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [compareError, setCompareError] = useState<string | null>(null);

  useEffect(() => {
    const fetchComparison = async () => {
      try {
        setCompareError(null);
        const response = await fetch(
          `${apiBase}/api/gauntlet/${result1.gauntlet_id}/compare/${result2.gauntlet_id}`,
        );
        if (response.ok) {
          const data = await response.json();
          setComparison(data);
        } else {
          setCompareError('Failed to load comparison. Please try again.');
        }
      } catch (err) {
        logger.error('Failed to fetch comparison:', err);
        setCompareError('Unable to compare results. Please check your connection.');
      } finally {
        setLoading(false);
      }
    };
    fetchComparison();
  }, [apiBase, result1.gauntlet_id, result2.gauntlet_id]);

  const calcDiff = (a: number, b: number) => {
    const diff = a - b;
    return diff > 0 ? `+${diff}` : diff.toString();
  };

  // Suppress unused variable warning
  void comparison;

  return (
    <div className="bg-surface border border-[var(--acid-cyan)]/30 rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-theme-data text-[var(--acid-cyan)] text-sm">COMPARISON VIEW</h3>
        <button
          onClick={onClose}
          className="text-text-muted hover:text-[var(--accent)] font-theme-data text-sm"
        >
          [CLOSE]
        </button>
      </div>

      {loading ? (
        <div className="text-center py-8 text-[var(--accent)] font-theme-data animate-pulse">
          Loading comparison...
        </div>
      ) : compareError ? (
        <div className="p-4 bg-warning/10 border border-warning/30 rounded text-warning font-theme-data text-sm">
          {compareError}
        </div>
      ) : (
        <div className="grid md:grid-cols-2 gap-6">
          {/* Result 1 */}
          <div className="p-4 border border-[var(--accent)]/30 rounded-lg">
            <div className="text-xs font-theme-data text-[var(--accent)] mb-2">RUN A</div>
            <VerdictBadge verdict={result1.verdict} />
            <div className="mt-4 space-y-2 text-sm font-theme-data">
              <div className="flex justify-between">
                <span className="text-text-muted">Critical:</span>
                <span className="text-acid-red">{result1.critical_count}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted">High:</span>
                <span className="text-warning">{result1.high_count}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted">Confidence:</span>
                <span className="text-text">{(result1.confidence * 100).toFixed(0)}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted">Robustness:</span>
                <span className="text-text">{(result1.robustness_score * 100).toFixed(0)}%</span>
              </div>
            </div>
          </div>

          {/* Result 2 */}
          <div className="p-4 border border-accent/30 rounded-lg">
            <div className="text-xs font-theme-data text-accent mb-2">RUN B</div>
            <VerdictBadge verdict={result2.verdict} />
            <div className="mt-4 space-y-2 text-sm font-theme-data">
              <div className="flex justify-between">
                <span className="text-text-muted">Critical:</span>
                <span className="text-acid-red">{result2.critical_count}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted">High:</span>
                <span className="text-warning">{result2.high_count}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted">Confidence:</span>
                <span className="text-text">{(result2.confidence * 100).toFixed(0)}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted">Robustness:</span>
                <span className="text-text">{(result2.robustness_score * 100).toFixed(0)}%</span>
              </div>
            </div>
          </div>

          {/* Delta */}
          <div className="md:col-span-2 p-4 bg-bg/50 border border-border rounded-lg">
            <div className="text-xs font-theme-data text-text-muted mb-3">DELTA (A - B)</div>
            <div className="grid grid-cols-4 gap-4 text-center">
              <div>
                <div
                  className={`text-lg font-theme-data ${result1.critical_count - result2.critical_count > 0 ? 'text-acid-red' : result1.critical_count - result2.critical_count < 0 ? 'text-[var(--accent)]' : 'text-text-muted'}`}
                >
                  {calcDiff(result1.critical_count, result2.critical_count)}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Critical</div>
              </div>
              <div>
                <div
                  className={`text-lg font-theme-data ${result1.high_count - result2.high_count > 0 ? 'text-warning' : result1.high_count - result2.high_count < 0 ? 'text-[var(--accent)]' : 'text-text-muted'}`}
                >
                  {calcDiff(result1.high_count, result2.high_count)}
                </div>
                <div className="text-xs font-theme-data text-text-muted">High</div>
              </div>
              <div>
                <div
                  className={`text-lg font-theme-data ${result1.total_findings - result2.total_findings > 0 ? 'text-[var(--acid-yellow)]' : result1.total_findings - result2.total_findings < 0 ? 'text-[var(--accent)]' : 'text-text-muted'}`}
                >
                  {calcDiff(result1.total_findings, result2.total_findings)}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Total</div>
              </div>
              <div>
                <div
                  className={`text-lg font-theme-data ${result1.robustness_score - result2.robustness_score > 0 ? 'text-[var(--accent)]' : result1.robustness_score - result2.robustness_score < 0 ? 'text-acid-red' : 'text-text-muted'}`}
                >
                  {((result1.robustness_score - result2.robustness_score) * 100).toFixed(0)}%
                </div>
                <div className="text-xs font-theme-data text-text-muted">Robustness</div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
