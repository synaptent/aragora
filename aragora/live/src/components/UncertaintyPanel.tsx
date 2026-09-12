'use client';

import { useState, useMemo, useCallback } from 'react';
import type { StreamEvent } from '@/types/events';

interface Crux {
  id?: string;
  claim: string;
  uncertainty: number;
  supporting_agents: string[];
  opposing_agents: string[];
  topic?: string;
}

interface UncertaintyAnalysisData {
  collective_confidence: number;
  confidence_interval: [number, number];
  disagreement_type: string;
  cruxes: Crux[];
  calibration_quality: number;
}

interface UncertaintyPanelProps {
  events?: StreamEvent[];
  debateId?: string;
  onFollowupCreated?: (followupId: string, task: string) => void;
}

export function UncertaintyPanel({
  events = [],
  debateId,
  onFollowupCreated,
}: UncertaintyPanelProps) {
  const [expanded, setExpanded] = useState(true);
  const [exploringCrux, setExploringCrux] = useState<string | null>(null);
  const [exploreError, setExploreError] = useState<string | null>(null);

  // Extract uncertainty_analysis events from stream
  const uncertaintyEvents = useMemo(
    () => events.filter((e) => e.type === 'uncertainty_analysis'),
    [events],
  );

  // Get the latest analysis
  const latestAnalysis = useMemo(() => {
    if (uncertaintyEvents.length === 0) return null;
    const latest = uncertaintyEvents[uncertaintyEvents.length - 1];
    return latest.data as UncertaintyAnalysisData;
  }, [uncertaintyEvents]);

  // Color based on confidence level
  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.8) return 'text-[var(--accent)]';
    if (confidence >= 0.6) return 'text-[var(--acid-cyan)]';
    if (confidence >= 0.4) return 'text-warning';
    return 'text-error';
  };

  // Color based on calibration quality
  const getCalibrationColor = (quality: number) => {
    if (quality >= 0.8) return 'text-[var(--accent)]';
    if (quality >= 0.6) return 'text-[var(--acid-cyan)]';
    if (quality >= 0.4) return 'text-warning';
    return 'text-error';
  };

  // Disagreement type badge color
  const getDisagreementColor = (type: string) => {
    switch (type) {
      case 'consensus':
        return 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40';
      case 'mild':
        return 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/40';
      case 'moderate':
        return 'bg-warning/20 text-warning border-warning/40';
      case 'severe':
      case 'polarized':
        return 'bg-error/20 text-error border-error/40';
      default:
        return 'bg-text-muted/20 text-text-muted border-text-muted/40';
    }
  };

  // Format confidence interval as percentage range
  const formatInterval = (interval: [number, number]) => {
    return `${(interval[0] * 100).toFixed(0)}%-${(interval[1] * 100).toFixed(0)}%`;
  };

  // Handle explore crux button click
  const handleExploreCrux = useCallback(
    async (crux: Crux, idx: number) => {
      if (!debateId) {
        setExploreError('No debate ID available');
        return;
      }

      const cruxId = crux.id || `crux-${idx}`;
      setExploringCrux(cruxId);
      setExploreError(null);

      try {
        const response = await fetch(`/api/debates/${debateId}/followup`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ crux_id: crux.id, task: `Resolve disagreement: ${crux.claim}` }),
        });

        if (!response.ok) {
          const error = await response.json();
          throw new Error(error.error || 'Failed to create follow-up debate');
        }

        const data = await response.json();
        onFollowupCreated?.(data.followup_id, data.task);
      } catch (err) {
        setExploreError(err instanceof Error ? err.message : 'Failed to create follow-up');
      } finally {
        setExploringCrux(null);
      }
    },
    [debateId, onFollowupCreated],
  );

  return (
    <div className="panel" style={{ padding: 0 }}>
      {/* Header */}
      <button onClick={() => setExpanded(!expanded)} className="panel-collapsible-header w-full">
        <div className="flex items-center gap-2">
          <span className="text-[var(--acid-cyan)] font-theme-data text-sm">[UNCERTAINTY]</span>
          <span className="text-text-muted text-xs">Disagreement analysis</span>
          {latestAnalysis && (
            <span
              className={`text-xs px-1 border ${getDisagreementColor(latestAnalysis.disagreement_type)}`}
            >
              {latestAnalysis.disagreement_type}
            </span>
          )}
        </div>
        <span className="panel-toggle">{expanded ? '[-]' : '[+]'}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3">
          {!latestAnalysis ? (
            <div className="text-text-muted text-xs text-center py-4">
              No uncertainty analysis available yet.
              <br />
              <span className="text-text-muted/60">Will appear after agents vote.</span>
            </div>
          ) : (
            <>
              {/* Key metrics */}
              <div className="grid grid-cols-3 gap-2">
                <div className="border border-[var(--accent)]/20 p-2 text-center">
                  <div className="text-xs text-text-muted">Confidence</div>
                  <div
                    className={`text-lg font-theme-data ${getConfidenceColor(latestAnalysis.collective_confidence)}`}
                  >
                    {(latestAnalysis.collective_confidence * 100).toFixed(0)}%
                  </div>
                  <div className="text-xs text-text-muted/60">
                    {formatInterval(latestAnalysis.confidence_interval)}
                  </div>
                </div>
                <div className="border border-[var(--accent)]/20 p-2 text-center">
                  <div className="text-xs text-text-muted">Disagreement</div>
                  <div
                    className={`text-sm font-theme-data capitalize ${getDisagreementColor(latestAnalysis.disagreement_type).split(' ')[1]}`}
                  >
                    {latestAnalysis.disagreement_type}
                  </div>
                  <div className="text-xs text-text-muted/60">
                    {latestAnalysis.cruxes.length} cruxes
                  </div>
                </div>
                <div className="border border-[var(--accent)]/20 p-2 text-center">
                  <div className="text-xs text-text-muted">Calibration</div>
                  <div
                    className={`text-lg font-theme-data ${getCalibrationColor(latestAnalysis.calibration_quality)}`}
                  >
                    {(latestAnalysis.calibration_quality * 100).toFixed(0)}%
                  </div>
                  <div className="text-xs text-text-muted/60">quality</div>
                </div>
              </div>

              {/* Confidence interval visualization */}
              <div className="space-y-1">
                <div className="text-xs text-text-muted">Confidence Range</div>
                <div className="h-4 bg-bg/50 relative border border-[var(--accent)]/20">
                  {/* Background scale markers */}
                  {[0.25, 0.5, 0.75].map((mark) => (
                    <div
                      key={mark}
                      className="absolute top-0 bottom-0 w-px bg-[var(--accent)]/10"
                      style={{ left: `${mark * 100}%` }}
                    />
                  ))}
                  {/* Interval bar */}
                  <div
                    className="absolute top-0 bottom-0 bg-[var(--acid-cyan)]/30"
                    style={{
                      left: `${latestAnalysis.confidence_interval[0] * 100}%`,
                      width: `${(latestAnalysis.confidence_interval[1] - latestAnalysis.confidence_interval[0]) * 100}%`,
                    }}
                  />
                  {/* Point estimate */}
                  <div
                    className="absolute top-0 bottom-0 w-0.5 bg-[var(--accent)]"
                    style={{ left: `${latestAnalysis.collective_confidence * 100}%` }}
                  />
                </div>
                <div className="flex justify-between text-xs text-text-muted/50">
                  <span>0%</span>
                  <span>50%</span>
                  <span>100%</span>
                </div>
              </div>

              {/* Disagreement cruxes */}
              {latestAnalysis.cruxes.length > 0 && (
                <div className="space-y-2">
                  <div className="text-xs text-text-muted">Key Disagreement Points</div>
                  {exploreError && (
                    <div className="text-xs text-error bg-error/10 border border-error/20 px-2 py-1">
                      {exploreError}
                    </div>
                  )}
                  <div className="space-y-1 max-h-48 overflow-y-auto">
                    {latestAnalysis.cruxes.map((crux, idx) => {
                      const cruxId = crux.id || `crux-${idx}`;
                      const isExploring = exploringCrux === cruxId;
                      return (
                        <div
                          key={idx}
                          className="border border-warning/20 bg-warning/5 p-2 text-xs"
                        >
                          <div className="flex justify-between items-start gap-2">
                            <span className="text-text flex-1">{crux.claim}</span>
                            <span
                              className={`shrink-0 ${getConfidenceColor(1 - crux.uncertainty)}`}
                            >
                              {(crux.uncertainty * 100).toFixed(0)}% uncertain
                            </span>
                          </div>
                          <div className="flex justify-between items-center mt-1">
                            <div className="flex gap-4 text-text-muted/70">
                              {crux.supporting_agents.length > 0 && (
                                <span className="text-[var(--accent)]/70">
                                  ✓ {crux.supporting_agents.join(', ')}
                                </span>
                              )}
                              {crux.opposing_agents.length > 0 && (
                                <span className="text-error/70">
                                  ✗ {crux.opposing_agents.join(', ')}
                                </span>
                              )}
                            </div>
                            {debateId && (
                              <button
                                onClick={() => handleExploreCrux(crux, idx)}
                                disabled={isExploring}
                                className={`px-2 py-0.5 text-xs font-theme-data border transition-colors ${
                                  isExploring
                                    ? 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/40 cursor-wait'
                                    : 'bg-[var(--accent)]/10 text-[var(--accent)] border-[var(--accent)]/30 hover:bg-[var(--accent)]/20'
                                }`}
                              >
                                {isExploring ? '[...]' : '[EXPLORE]'}
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Explanation */}
              <div className="text-xs text-text-muted/50 text-center border-t border-[var(--accent)]/10 pt-2">
                {latestAnalysis.disagreement_type === 'consensus' &&
                  'Agents broadly agree on the conclusion.'}
                {latestAnalysis.disagreement_type === 'mild' &&
                  'Minor disagreements exist but overall direction is clear.'}
                {latestAnalysis.disagreement_type === 'moderate' &&
                  'Significant disagreements warrant further debate.'}
                {(latestAnalysis.disagreement_type === 'severe' ||
                  latestAnalysis.disagreement_type === 'polarized') &&
                  'Deep disagreement detected. Consider a follow-up debate on cruxes.'}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
