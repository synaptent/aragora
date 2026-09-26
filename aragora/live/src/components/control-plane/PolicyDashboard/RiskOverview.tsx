'use client';

import { useMemo } from 'react';
import type { ComplianceFramework } from './ComplianceFrameworkList';
import type { ComplianceViolation } from './ViolationTracker';

export interface RiskOverviewProps {
  frameworks: ComplianceFramework[];
  violations: ComplianceViolation[];
  verticals: Array<{ id: string; name: string }>;
  showDetails?: boolean;
  className?: string;
}

export function RiskOverview({
  frameworks,
  violations,
  verticals,
  showDetails = false,
  className = '',
}: RiskOverviewProps) {
  const riskByVertical = useMemo(() => {
    return verticals
      .map((v) => {
        const vViolations = violations.filter(
          (viol) => viol.vertical_id === v.id && viol.status !== 'resolved',
        );
        const critical = vViolations.filter((viol) => viol.severity === 'critical').length;
        const high = vViolations.filter((viol) => viol.severity === 'high').length;
        const medium = vViolations.filter((viol) => viol.severity === 'medium').length;
        const low = vViolations.filter((viol) => viol.severity === 'low').length;
        const score = Math.min(100, critical * 25 + high * 10 + medium * 5 + low * 2);
        const vFrameworks = frameworks.filter((fw) => fw.vertical_id === v.id);

        return {
          ...v,
          violations: vViolations.length,
          critical,
          high,
          medium,
          low,
          score,
          frameworksCount: vFrameworks.length,
        };
      })
      .sort((a, b) => b.score - a.score);
  }, [verticals, violations, frameworks]);

  const overallScore = useMemo(() => {
    const open = violations.filter((v) => v.status !== 'resolved');
    return Math.min(
      100,
      open.filter((v) => v.severity === 'critical').length * 25 +
        open.filter((v) => v.severity === 'high').length * 10 +
        open.filter((v) => v.severity === 'medium').length * 5 +
        open.filter((v) => v.severity === 'low').length * 2,
    );
  }, [violations]);

  const getScoreColor = (score: number) => {
    if (score > 70) return 'text-red-400';
    if (score > 40) return 'text-yellow-400';
    return 'text-green-400';
  };

  const getScoreBg = (score: number) => {
    if (score > 70) return 'bg-red-900/30';
    if (score > 40) return 'bg-yellow-900/30';
    return 'bg-green-900/30';
  };

  return (
    <div className={className}>
      {/* Overall risk gauge */}
      <div className="flex items-center justify-center mb-6">
        <div className="text-center">
          <div className={`text-6xl font-theme-data font-bold ${getScoreColor(overallScore)}`}>
            {overallScore}
          </div>
          <div className="text-sm text-text-muted mt-1">Overall Risk Score</div>
          <div className="w-48 h-2 bg-surface rounded-full mt-3 overflow-hidden">
            <div
              className={`h-full transition-all ${getScoreBg(overallScore)}`}
              style={{ width: `${overallScore}%` }}
            />
          </div>
        </div>
      </div>

      {/* Risk by vertical */}
      <h3 className="font-theme-data font-bold text-text mb-3">Risk by Vertical</h3>
      <div className="space-y-3">
        {riskByVertical.map((v) => (
          <div key={v.id} className="p-3 bg-bg border border-border rounded-lg">
            <div className="flex items-center justify-between mb-2">
              <span className="font-theme-data font-bold text-text">{v.name}</span>
              <span className={`text-lg font-theme-data font-bold ${getScoreColor(v.score)}`}>
                {v.score}
              </span>
            </div>
            <div className="w-full h-1.5 bg-surface rounded-full overflow-hidden mb-2">
              <div
                className={`h-full transition-all ${getScoreBg(v.score)}`}
                style={{ width: `${v.score}%` }}
              />
            </div>
            <div className="flex items-center gap-4 text-xs text-text-muted">
              <span>{v.frameworksCount} frameworks</span>
              <span>{v.violations} violations</span>
              {v.critical > 0 && <span className="text-red-400">{v.critical} critical</span>}
              {v.high > 0 && <span className="text-orange-400">{v.high} high</span>}
            </div>
            {showDetails && v.violations > 0 && (
              <div className="mt-3 pt-3 border-t border-border">
                <div className="grid grid-cols-4 gap-2 text-xs">
                  <div className="text-center">
                    <span className="text-red-400 font-bold">{v.critical}</span>
                    <br />
                    Critical
                  </div>
                  <div className="text-center">
                    <span className="text-orange-400 font-bold">{v.high}</span>
                    <br />
                    High
                  </div>
                  <div className="text-center">
                    <span className="text-yellow-400 font-bold">{v.medium}</span>
                    <br />
                    Medium
                  </div>
                  <div className="text-center">
                    <span className="text-blue-400 font-bold">{v.low}</span>
                    <br />
                    Low
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Risk legend */}
      <div className="mt-6 p-3 bg-bg border border-border rounded-lg">
        <h4 className="font-theme-data text-xs text-text-muted mb-2">RISK SCORE CALCULATION</h4>
        <div className="grid grid-cols-4 gap-2 text-xs">
          <div>
            <span className="text-red-400">Critical</span>: 25 pts
          </div>
          <div>
            <span className="text-orange-400">High</span>: 10 pts
          </div>
          <div>
            <span className="text-yellow-400">Medium</span>: 5 pts
          </div>
          <div>
            <span className="text-blue-400">Low</span>: 2 pts
          </div>
        </div>
        <div className="flex items-center gap-4 mt-2 text-xs text-text-muted">
          <span>
            <span className="text-green-400">0-40</span>: Low Risk
          </span>
          <span>
            <span className="text-yellow-400">41-70</span>: Medium Risk
          </span>
          <span>
            <span className="text-red-400">71+</span>: High Risk
          </span>
        </div>
      </div>
    </div>
  );
}
