'use client';

/**
 * OraclePhaseProgress — Visual stepper for the Oracle's four streaming phases.
 *
 * Renders a horizontal progress indicator:
 *   [checkmark Reflex] ----> [pulse Deep] ----> [dim Tentacles] ----> [dim Synthesis]
 *
 * Completed phases show a green checkmark, the active phase pulses with magenta
 * glow, and upcoming phases are dimmed. Connector lines between steps fill green
 * as phases complete.
 *
 * Usage:
 *   <OraclePhaseProgress currentPhase="deep" />
 */

import type { OraclePhase } from '@/hooks/useOracleWebSocket';

// ---------------------------------------------------------------------------
// Phase metadata
// ---------------------------------------------------------------------------

interface PhaseInfo {
  key: OraclePhase;
  label: string;
  desc: string;
  icon: string;
}

const PHASES: PhaseInfo[] = [
  { key: 'reflex', label: 'REFLEX', desc: 'Quick response', icon: '\u26A1' },
  { key: 'deep', label: 'DEEP', desc: 'Detailed analysis', icon: '\u{1F9E0}' },
  { key: 'tentacles', label: 'DEBATE', desc: 'Multi-agent debate', icon: '\u{1F419}' },
  { key: 'synthesis', label: 'SYNTHESIS', desc: 'Convergence', icon: '\u{1F52E}' },
];

const PHASE_ORDER: OraclePhase[] = PHASES.map((p) => p.key);

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface OraclePhaseProgressProps {
  /** The currently active Oracle phase. Hidden when 'idle'. */
  currentPhase: OraclePhase;
}

export function OraclePhaseProgress({ currentPhase }: OraclePhaseProgressProps) {
  if (currentPhase === 'idle') return null;

  const currentIdx = PHASE_ORDER.indexOf(currentPhase);

  return (
    <div className="mb-6" role="progressbar" aria-label="Oracle phase progress">
      {/* Oracle-specific keyframes for the glow pulse */}
      <style>{`
        @keyframes oracle-phase-glow {
          0%, 100% { box-shadow: 0 0 6px rgba(255, 0, 255, 0.3); }
          50% { box-shadow: 0 0 16px rgba(255, 0, 255, 0.6), 0 0 30px rgba(255, 0, 255, 0.2); }
        }
        .oracle-phase-active {
          animation: oracle-phase-glow 2s ease-in-out infinite;
        }
      `}</style>

      <div className="flex items-center gap-1">
        {PHASES.map((phase, idx) => {
          const isComplete = idx < currentIdx;
          const isActive = idx === currentIdx;

          return (
            <div key={phase.key} className="flex items-center flex-1">
              {/* Step circle + label */}
              <div className="flex flex-col items-center flex-1 min-w-0">
                <div
                  className={[
                    'w-8 h-8 rounded-full border-2 flex items-center justify-center',
                    'text-xs font-theme-data font-bold transition-all duration-500',
                    isComplete
                      ? 'border-[var(--acid-green)] bg-[var(--acid-green)]/20 text-[var(--acid-green)]'
                      : isActive
                        ? 'border-[var(--acid-magenta)] bg-[var(--acid-magenta)]/20 text-[var(--acid-magenta)] oracle-phase-active'
                        : 'border-[var(--border)] bg-transparent text-[var(--text-muted)]/40',
                  ].join(' ')}
                >
                  {isComplete ? (
                    <span className="text-[11px]">{'\u2713'}</span>
                  ) : (
                    <span className="text-[11px]">{phase.icon}</span>
                  )}
                </div>
                <span
                  className={[
                    'text-[9px] font-theme-data mt-1.5 tracking-wider transition-colors duration-500',
                    isActive
                      ? 'text-[var(--acid-magenta)]'
                      : isComplete
                        ? 'text-[var(--acid-green)]'
                        : 'text-[var(--text-muted)]/40',
                  ].join(' ')}
                >
                  {phase.label}
                </span>
                <span
                  className={[
                    'text-[8px] transition-colors duration-500',
                    isActive ? 'text-[var(--text-muted)]/70' : 'text-[var(--text-muted)]/40',
                  ].join(' ')}
                >
                  {phase.desc}
                </span>
              </div>

              {/* Connector line between steps */}
              {idx < PHASES.length - 1 && (
                <div
                  className={[
                    'h-[2px] flex-1 mx-1 transition-all duration-700',
                    isComplete ? 'bg-[var(--acid-green)]/60' : 'bg-[var(--border)]/30',
                  ].join(' ')}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default OraclePhaseProgress;
